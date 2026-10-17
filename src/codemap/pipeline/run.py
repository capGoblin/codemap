"""Fixed-step orchestrator: walk, split, validate, save (spec 6).

Split workers run only `split_steps`. Every store write and `ctx.emit` call happens on the
calling thread, because the store connection belongs to it.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from codemap.domain.events import Event, EventKind
from codemap.domain.models import Anchor, Effect, Node, TraceMode, TraceStatus
from codemap.domain.rules import anchor_contains, drop_ratio, path_points, side_hops
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


def _split_all_steps(
    ctx: TraceContext, phases: list[Node], effects: list[Effect]
) -> list[tuple[list[Node], str | None]]:
    with ThreadPoolExecutor(ctx.settings.split_concurrency) as pool:
        futures = [pool.submit(split_steps, ctx, p, effects) for p in phases]
        return [f.result() for f in futures]


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
    _emit(ctx, "step_started", "split_phases")
    phases, reason = split_phases(ctx, question, points, walk.effects)
    if reason:
        reasons.append(f"split phases: {reason}")
    for p in phases:
        _emit(ctx, "phase_split", p.title, phase_id=p.id)

    steps: list[Node] = []
    edges = phase_edges(phases, walk.hops)
    if mode == "eager" and phases:
        _emit(ctx, "step_started", "split_steps")
        for phase, (kids, why) in zip(
            phases, _split_all_steps(ctx, phases, walk.effects), strict=True
        ):
            if why:
                reasons.append(f"split steps for {phase.title}: {why}")
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
    for warning in report.warnings:
        _emit(ctx, "warning", warning)

    _emit(ctx, "step_started", "save")
    store.save_nodes(tid, report.nodes, report.edges)
    budget = ctx.budget
    store.set_totals(tid, budget.input_tokens, budget.output_tokens, budget.cost_usd)

    phase_ids = {p.id for p in phases}
    survivors = sum(1 for n in report.nodes if n.id in phase_ids)
    ratio = drop_ratio(len(report.nodes), report.dropped)
    if ratio > PARTIAL_DROP_RATIO:
        total = len(report.nodes) + report.dropped
        reasons.append(f"validation dropped {report.dropped} of {total} nodes")
    status = _status(survivors, reasons, ratio)
    store.set_status(tid, status)
    _emit(ctx, "finished", "; ".join(reasons), status=status)
    return status


def expand_phase(ctx: TraceContext, phase_id: str) -> list[Node]:
    """Split one stored phase into steps (lazy mode). Raises KeyError for an unknown phase."""
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
        return []

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
    for warning in report.warnings:
        _emit(ctx, "warning", warning)
    children = [n for n in report.nodes if n.parent_id == phase.id]
    child_ids = {n.id for n in children}
    edges = [e for e in report.edges if e.target_id in child_ids]
    store.replace_children(tid, phase.id, children, edges)
    _emit(ctx, "phase_split", phase.title, phase_id=phase.id, steps=len(children))
    return children
