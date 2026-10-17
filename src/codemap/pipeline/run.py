"""Fixed-step orchestrator: walk, split, validate, save (spec 6).

Split workers run only `split_steps`. Every store write and `ctx.emit` call happens on the
calling thread. Workers reach the store only through the model-call and symbol caches, which
share the connection lock.
"""

import queue
import threading
import uuid
from datetime import UTC, datetime

from codemap.domain.events import Event, EventKind
from codemap.domain.models import Anchor, Effect, Node, TraceMode, TraceStatus
from codemap.domain.rules import (
    anchor_contains,
    assign_effects,
    drop_ratio,
    path_points,
    side_hops,
    unreachable_hops,
)
from codemap.pipeline.context import TraceContext
from codemap.pipeline.split import (
    phase_edges,
    side_nodes,
    split_phases,
    split_steps,
    steps_edges,
)
from codemap.pipeline.validate import PARTIAL_DROP_RATIO, validate_graph
from codemap.pipeline.walk import walk_path


def _emit(ctx: TraceContext, kind: EventKind, message: str, **data: object) -> None:
    ctx.emit(
        Event(trace_id=ctx.trace_id, kind=kind, message=message, data=data, at=datetime.now(UTC))
    )


class ExpandError(Exception):
    """A lazy expand could not split the phase. The message is the reason."""


StepResult = tuple[list[Node], str | None]
POLL_SECONDS = 0.1


def _split_all_steps(
    ctx: TraceContext, phases: list[Node], effects: list[Effect]
) -> list[StepResult]:
    """Split every phase on daemon threads. A cancel returns at once with "cancelled"."""
    results: list[StepResult] = [([], "cancelled")] * len(phases)
    todo: queue.Queue[int] = queue.Queue()
    for i in range(len(phases)):
        todo.put(i)
    errors: list[BaseException] = []

    def work() -> None:
        while not ctx.cancel.is_set():
            try:
                i = todo.get_nowait()
            except queue.Empty:
                return
            try:
                results[i] = split_steps(ctx, phases[i], effects)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
                errors.append(exc)
                return

    threads = [
        threading.Thread(target=work, daemon=True)
        for _ in range(min(ctx.settings.split_concurrency, len(phases)))
    ]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads) and not ctx.cancel.is_set():
        ctx.cancel.wait(POLL_SECONDS)
    if errors:
        raise errors[0]
    return list(results)


def _fallback_phases(points: list[Anchor], effects: list[Effect], reason: str) -> list[Node]:
    """One phase per path point, so a failed phase split still shows the walk."""
    return [
        Node(
            id=uuid.uuid4().hex,
            level=0,
            parent_id=None,
            order=i,
            title=point.symbol,
            does="",
            input="",
            output="",
            boundary_reason=f"split failed: {reason}",
            anchors=(point,),
            effects=assign_effects([point], effects),
        )
        for i, point in enumerate(points)
    ]


def _status(survivors: int, reasons: list[str], ratio: float) -> TraceStatus:
    if survivors == 0:
        return "failed"
    return "partial" if reasons or ratio > PARTIAL_DROP_RATIO else "complete"


def run_trace(ctx: TraceContext, question: str, entry: Anchor, mode: TraceMode) -> TraceStatus:
    store, tid = ctx.store, ctx.trace_id
    reasons: list[str] = []

    _emit(ctx, "step_started", "walk")
    walk = walk_path(ctx, entry, question)
    if walk.partial_reason:
        reasons.append(f"walk: {walk.partial_reason}")

    points = path_points(entry, walk.hops)
    for lost in unreachable_hops(points, walk.hops):
        _emit(
            ctx,
            "warning",
            f"hop not reachable from the entry, so not shown: "
            f"{lost.caller.symbol} -> {lost.callee.symbol}",
        )
    _emit(ctx, "step_started", "split_phases")
    phases, reason = split_phases(ctx, question, points, walk.effects)
    if reason:
        reasons.append(f"split phases: {reason}")
        if walk.hops:
            phases = _fallback_phases(points, walk.effects, reason)
    for p in phases:
        _emit(ctx, "phase_split", p.title, phase_id=p.id)

    steps: list[Node] = []
    edges = phase_edges(phases, walk.hops)
    if phases:
        store.save_nodes(tid, phases, edges)  # saved now so a crash or Ctrl-C keeps the phases
    if mode == "eager" and phases and not reason:
        _emit(ctx, "step_started", "split_steps")
        results = _split_all_steps(ctx, phases, walk.effects)
        for i, (kids, why) in enumerate(results):
            phase = phases[i]
            if why:
                reasons.append(f"split steps for {phase.title}: {why}")
                phase = phases[i] = phase.model_copy(
                    update={"warnings": (*phase.warnings, f"steps unavailable: {why}")}
                )
            steps.extend(kids)
            edges.extend(steps_edges(kids))
            _emit(ctx, "phase_split", phase.title, phase_id=phase.id, steps=len(kids))

    sides, side_edges = side_nodes(side_hops(walk.hops), [*phases, *steps])
    _emit(ctx, "step_started", "validate")
    report = validate_graph(
        ctx.tools,
        [*phases, *steps, *sides],
        [*edges, *side_edges],
        points,
        {n.id for n in sides},
    )
    for warning in [*report.warnings, *report.drops]:
        _emit(ctx, "warning", warning)

    _emit(ctx, "step_started", "save")
    store.replace_graph(tid, report.nodes, report.edges)
    budget = ctx.budget
    store.set_totals(tid, budget.input_tokens, budget.output_tokens, budget.cost_usd)

    phase_ids = {p.id for p in phases}
    survivors = sum(1 for n in report.nodes if n.id in phase_ids)
    ratio = drop_ratio(len(report.nodes), report.dropped)
    if ratio > PARTIAL_DROP_RATIO:
        total = len(report.nodes) + report.dropped
        reasons.append(f"validation dropped {report.dropped} of {total} nodes")
    status = _status(survivors, reasons, ratio)
    if ctx.cancel.is_set():
        status = "partial"  # a user stop is never complete, and never failed
        if not reasons:
            reasons.append("cancelled")
    store.set_status(tid, status)
    _emit(ctx, "finished", "; ".join(reasons), status=status)
    return status


def expand_phase(ctx: TraceContext, phase_id: str) -> list[Node]:
    """Split one stored phase into steps (lazy mode).

    Raises KeyError for an unknown phase and ExpandError when the split fails.
    """
    store, tid = ctx.store, ctx.trace_id
    phase = store.get_node(tid, phase_id)
    if phase is None or phase.level != 0:
        raise KeyError(phase_id)
    hops = store.get_hops(tid)
    trace = store.get_trace(tid)
    if trace is None:
        raise KeyError(tid)
    points = path_points(trace.entry, hops)

    steps, reason = split_steps(ctx, phase, store.get_walk_effects(tid))
    if reason:
        _emit(ctx, "warning", f"split steps for {phase.title}: {reason}")
        raise ExpandError(reason)

    # Hops whose caller lies in a step. Phase-level side nodes were stored by the trace run.
    in_phase = [
        h for h in side_hops(hops) if any(anchor_contains(a, h.caller) for a in phase.anchors)
    ]
    sides, side_edges = side_nodes(in_phase, [phase, *steps])
    sides = [s for s in sides if s.parent_id == phase.id]
    side_ids = {s.id for s in sides}
    side_edges = [e for e in side_edges if e.target_id in side_ids]

    report = validate_graph(
        ctx.tools,
        [phase, *steps, *sides],
        [*steps_edges(steps), *side_edges],
        points,
        side_ids,
    )
    for warning in [*report.warnings, *report.drops]:
        _emit(ctx, "warning", warning)
    children = [n for n in report.nodes if n.parent_id == phase.id]
    child_ids = {n.id for n in children}
    edges = [e for e in report.edges if e.target_id in child_ids]
    store.replace_children(tid, phase.id, children, edges)
    _emit(ctx, "phase_split", phase.title, phase_id=phase.id, steps=len(children))
    return children
