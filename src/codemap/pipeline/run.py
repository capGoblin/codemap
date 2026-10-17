"""Orchestrator: skeleton walk, phases, deepen walk per phase, recursive split, validate, save.

Deepen walks run one after another on the calling thread, because walk tools write the store.
Child splits run on worker threads that only call `split_children`. Every store write and
`ctx.emit` call happens on the calling thread. Workers reach the store only through the
model-call and symbol caches, which share the connection lock.
"""

import queue
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from codemap.domain.events import Event, EventKind
from codemap.domain.models import Anchor, Edge, Effect, Hop, Node, TraceMode, TraceStatus
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
    split_children,
    split_phases,
    steps_edges,
    subpath_points,
)
from codemap.pipeline.validate import PARTIAL_DROP_RATIO, validate_graph
from codemap.pipeline.walk import deepen_budgets, next_budget, walk_deepen, walk_skeleton

EAGER_MAX_LEVEL = 2  # levels 0, 1, 2 are built in a run; deeper ones on demand
MIN_SUBPATH_POINTS = 3
EXPAND_HOPS = 20
POLL_SECONDS = 0.1


def _emit(ctx: TraceContext, kind: EventKind, message: str, **data: object) -> None:
    ctx.emit(
        Event(trace_id=ctx.trace_id, kind=kind, message=message, data=data, at=datetime.now(UTC))
    )


class ExpandError(Exception):
    """A lazy expand could not split the node. The message is the reason."""


StepResult = tuple[list[Node], str | None]
Job = tuple[Node, list[Anchor]]


def _split_jobs(
    ctx: TraceContext,
    jobs: list[Job],
    effects: list[Effect],
    on_done: Callable[[int, StepResult], None],
) -> None:
    """Split every job on daemon threads. `on_done` runs on the calling thread per result.

    A cancel returns at once. Jobs not finished are not reported.
    """
    todo: queue.Queue[int] = queue.Queue()
    for i in range(len(jobs)):
        todo.put(i)
    done: queue.Queue[tuple[int, StepResult | BaseException]] = queue.Queue()

    def work() -> None:
        while not ctx.cancel.is_set():
            try:
                i = todo.get_nowait()
            except queue.Empty:
                return
            try:
                parent, points = jobs[i]
                done.put((i, split_children(ctx, parent, points, effects)))
            except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
                done.put((i, exc))
                return

    threads = [
        threading.Thread(target=work, daemon=True)
        for _ in range(min(ctx.settings.split_concurrency, len(jobs)))
    ]
    for t in threads:
        t.start()
    reported = 0
    while reported < len(jobs) and not ctx.cancel.is_set():
        try:
            i, result = done.get(timeout=POLL_SECONDS)
        except queue.Empty:
            if not any(t.is_alive() for t in threads) and done.empty():
                return
            continue
        if isinstance(result, BaseException):
            raise result
        reported += 1
        on_done(i, result)


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


def _swap(nodes: list[Node], new: Node) -> None:
    nodes[:] = [new if n.id == new.id else n for n in nodes]


def _scope(node: Node, hops: list[Hop]) -> list[Anchor]:
    """Anchors whose effects belong to the node: its own and the callees recorded inside it."""
    inside = [h.callee for h in hops if any(anchor_contains(a, h.caller) for a in node.anchors)]
    return [*node.anchors, *inside]


def _eligible(node: Node, hops: list[Hop]) -> bool:
    return node.level < EAGER_MAX_LEVEL and len(subpath_points(node, hops)) >= MIN_SUBPATH_POINTS


def _deepen_all(
    ctx: TraceContext, question: str, phases: list[Node], skeleton: list[Hop], reasons: list[str]
) -> tuple[list[Hop], list[Effect]]:
    """Walk inside each phase in turn. Unused hops carry over to the next phase."""
    budgets = deepen_budgets(phases, ctx.settings.deepen_hops)
    hops: list[Hop] = []
    effects: list[Effect] = []
    carry = 0
    for phase, base in zip(phases, budgets, strict=True):
        if ctx.cancel.is_set():
            break
        budget = next_budget(base, carry)
        known = [h for h in skeleton if any(anchor_contains(a, h.caller) for a in phase.anchors)]
        walk = walk_deepen(ctx, phase, question, budget, known)
        carry = max(0, budget - len(walk.hops))
        hops.extend(walk.hops)
        effects.extend(walk.effects)
        if walk.partial_reason:
            reasons.append(f"deepen {phase.title}: {walk.partial_reason}")
    return hops, effects


def _split_level(
    ctx: TraceContext,
    parents: list[Node],
    hops: list[Hop],
    effects: list[Effect],
    nodes: list[Node],
    edges: list[Edge],
    reasons: list[str],
) -> list[Node]:
    """Split every parent into children, saving each parent's children as they arrive."""
    jobs: list[Job] = [(p, subpath_points(p, hops) or list(p.anchors)) for p in parents]
    level_kids: list[Node] = []

    def done(i: int, result: StepResult) -> None:
        parent = jobs[i][0]
        kids, why = result
        if why:
            reasons.append(f"split steps for {parent.title}: {why}")
            note = f"steps unavailable: {why}"
            _swap(nodes, parent.model_copy(update={"warnings": (*parent.warnings, note)}))
        kid_edges = steps_edges(kids)
        if kids:
            ctx.store.save_nodes(ctx.trace_id, kids, kid_edges)  # a crash keeps the children
        nodes.extend(kids)
        edges.extend(kid_edges)
        level_kids.extend(kids)
        _emit(ctx, "phase_split", parent.title, phase_id=parent.id, steps=len(kids))

    _split_jobs(ctx, jobs, effects, done)
    return level_kids


def run_trace(ctx: TraceContext, question: str, entry: Anchor, mode: TraceMode) -> TraceStatus:
    store, tid = ctx.store, ctx.trace_id
    reasons: list[str] = []

    _emit(ctx, "step_started", "walk")
    skeleton = walk_skeleton(ctx, entry, question)
    if skeleton.partial_reason:
        reasons.append(f"walk: {skeleton.partial_reason}")

    points = path_points(entry, skeleton.hops)
    for lost in unreachable_hops(points, skeleton.hops):
        _emit(
            ctx,
            "warning",
            f"hop not reachable from the entry, so not shown: "
            f"{lost.caller.symbol} -> {lost.callee.symbol}",
        )
    _emit(ctx, "step_started", "split_phases")
    phases, reason = split_phases(ctx, question, points, skeleton.effects)
    if reason:
        reasons.append(f"split phases: {reason}")
        if skeleton.hops:
            phases = _fallback_phases(points, skeleton.effects, reason)
    for p in phases:
        _emit(ctx, "phase_split", p.title, phase_id=p.id)

    hops, effects = list(skeleton.hops), list(skeleton.effects)
    on_path = list(points)
    nodes: list[Node] = list(phases)
    edges = phase_edges(phases, skeleton.hops)
    if phases:
        store.save_nodes(tid, phases, edges)  # saved now so a crash or Ctrl-C keeps the phases
    if mode == "eager" and phases and not reason:
        _emit(ctx, "step_started", "deepen")
        deep_hops, deep_effects = _deepen_all(ctx, question, phases, skeleton.hops, reasons)
        hops += deep_hops
        effects += deep_effects
        on_path += [a for h in deep_hops if h.verdict != "rejected" for a in (h.caller, h.callee)]
        for phase in phases:
            _swap(
                nodes,
                phase.model_copy(update={"effects": assign_effects(_scope(phase, hops), effects)}),
            )
        phases = [n for n in nodes if n.level == 0]

        _emit(ctx, "step_started", "split_steps")
        parents = phases
        while parents and not ctx.cancel.is_set():
            kids = _split_level(ctx, parents, hops, effects, nodes, edges, reasons)
            parents = [k for k in kids if _eligible(k, hops)]

    sides, side_edges = side_nodes(side_hops(hops), nodes)
    _emit(ctx, "step_started", "validate")
    report = validate_graph(
        ctx.tools,
        [*nodes, *sides],
        [*edges, *side_edges],
        on_path,
        {n.id for n in sides},
    )
    for warning in [*report.warnings, *report.drops]:
        _emit(ctx, "warning", warning)

    _emit(ctx, "step_started", "save")
    store.replace_graph(tid, report.nodes, report.edges)
    budget = ctx.budget
    store.set_totals(tid, budget.input_tokens, budget.output_tokens, budget.cost_usd)

    survivors = sum(1 for n in report.nodes if n.level == 0)
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


def expand_node(ctx: TraceContext, node_id: str) -> list[Node]:
    """Build the children of one stored node at any level, replacing its old children.

    With fewer than 3 sub-path points, walk inside the node first. Raises KeyError for an
    unknown node and ExpandError when the split fails.
    """
    store, tid = ctx.store, ctx.trace_id
    node = store.get_node(tid, node_id)
    trace = store.get_trace(tid)
    if node is None or trace is None:
        raise KeyError(node_id)
    hops = store.get_hops(tid)
    new_hops: list[Hop] = []
    if len(subpath_points(node, hops)) < MIN_SUBPATH_POINTS:
        known = [h for h in hops if any(anchor_contains(a, h.caller) for a in node.anchors)]
        walk = walk_deepen(ctx, node, trace.question, EXPAND_HOPS, known)
        new_hops = walk.hops
        if walk.partial_reason:
            _emit(ctx, "warning", f"deepen {node.title}: {walk.partial_reason}")
        hops = store.get_hops(tid)
    effects = store.get_walk_effects(tid)
    points = subpath_points(node, hops) or list(node.anchors)

    children, reason = split_children(ctx, node, points, effects)
    if reason:
        _emit(ctx, "warning", f"split steps for {node.title}: {reason}")
        raise ExpandError(reason)

    in_node = [
        h for h in side_hops(hops) if any(anchor_contains(a, h.caller) for a in node.anchors)
    ]
    sides, side_edges = side_nodes(in_node, [node, *children])
    sides = [s for s in sides if s.parent_id == node.id]
    side_ids = {s.id for s in sides}
    side_edges = [e for e in side_edges if e.target_id in side_ids]

    on_path = [
        *path_points(trace.entry, hops),
        *(a for h in new_hops if h.verdict != "rejected" for a in (h.caller, h.callee)),
    ]
    report = validate_graph(
        ctx.tools,
        [*children, *sides],
        [*steps_edges(children), *side_edges],
        on_path,
        side_ids,
        context=[node],
    )
    for warning in [*report.warnings, *report.drops]:
        _emit(ctx, "warning", warning)
    kept = [n for n in report.nodes if n.parent_id == node.id]
    kept_ids = {n.id for n in kept}
    store.replace_children(tid, node.id, kept, [e for e in report.edges if e.target_id in kept_ids])
    _emit(ctx, "phase_split", node.title, phase_id=node.id, steps=len(kept))
    return kept
