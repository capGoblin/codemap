"""Explain one node in plain words. One model call, no tools.

The model writes steps and the input and output sides. Code drops every step whose cite lies
outside the node's anchors and the recorded calls made from them, and clears a node id that
does not exist. Nothing here emits events.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from codemap.agents.loop import run_tool_loop
from codemap.agents.schema import tolerant_list
from codemap.domain.models import (
    Anchor,
    CallLink,
    Effect,
    ExplainStep,
    Hop,
    IoSide,
    Node,
    NodeExplain,
)
from codemap.domain.rules import anchor_contains, anchors_overlap
from codemap.pipeline.context import TraceContext, prompt
from codemap.pipeline.split import phase_code

EXPLAIN_MAX_TURNS = 3
ALL_LEVELS = 1_000_000


class ExplainError(Exception):
    """The model answered, but no step survived grounding."""


class ExplainSubmit(BaseModel):
    steps: list[ExplainStep]
    input: IoSide = IoSide()
    output: IoSide = IoSide()

    _unwrap = tolerant_list("steps")


def _live(hops: Sequence[Hop]) -> list[Hop]:
    return [h for h in hops if h.verdict != "rejected"]


def _citable(node: Node, hops: Sequence[Hop]) -> list[Anchor]:
    """The node's anchors, plus the caller range of each recorded hop made from them."""
    callers = [
        h.caller for h in _live(hops) if any(anchors_overlap(h.caller, a) for a in node.anchors)
    ]
    return [*node.anchors, *callers]


def _grounded(step: ExplainStep, allowed: Sequence[Anchor]) -> bool:
    first, last = step.lines
    if not 1 <= first <= last:
        return False
    cite = Anchor(file=step.file, start_line=first, end_line=last, symbol="")
    return any(anchor_contains(a, cite) for a in allowed)


def _known(side: IoSide, ids: set[str]) -> IoSide:
    return (
        side
        if side.node_id in ids or side.node_id is None
        else side.model_copy(update={"node_id": None})
    )


def _titles(nodes: Sequence[Node], node: Node) -> str:
    parent = next((n.title for n in nodes if n.id == node.parent_id), "none")
    siblings = [n for n in nodes if n.parent_id == node.parent_id and n.id != node.id]
    rows = "\n".join(f"- {n.id}: {n.title}" for n in sorted(siblings, key=lambda n: n.order))
    return f"Parent: {parent}\nOther nodes (id: title):\n{rows or '- none'}"


def _hop_rows(node: Node, hops: Sequence[Hop]) -> str:
    rows = [
        f"- {h.caller.file}:{h.caller.start_line}-{h.caller.end_line} {h.caller.symbol} "
        f"calls {h.callee.symbol} ({h.kind})"
        for h in _live(hops)
        if any(anchors_overlap(h.caller, a) for a in node.anchors)
    ]
    return "\n".join(rows) or "- none"


def _effect_rows(effects: Sequence[Effect]) -> str:
    rows = [
        f"- {e.op} {e.category} {e.target} {e.anchor.file}:{e.anchor.start_line}" for e in effects
    ]
    return "\n".join(rows) or "- none"


def explain_node(
    ctx: TraceContext, node: Node, hops: Sequence[Hop], effects: Sequence[Effect]
) -> NodeExplain:
    """Raise LimitReached or ModelError on a failed call, ExplainError when nothing is grounded."""
    nodes = ctx.store.get_graph(ctx.trace_id, ALL_LEVELS).nodes
    user = (
        f"Node: {node.title}\n{node.summary or node.does}\n"
        f"Id: {node.id}\n{_titles(nodes, node)}\n\n"
        f"Recorded calls:\n{_hop_rows(node, hops)}\n\n"
        f"Data touched:\n{_effect_rows(effects)}\n\n"
        f"Code:\n{phase_code(ctx.tools, node)}"
    )
    sub = run_tool_loop(
        ctx.model,
        system=prompt("explain"),
        user=user,
        tools=[],
        submit_schema=ExplainSubmit,
        budget=ctx.budget,
        max_turns=EXPLAIN_MAX_TURNS,
    )
    allowed = _citable(node, hops)
    steps = tuple(s for s in sub.steps if _grounded(s, allowed))
    if not steps:
        raise ExplainError("no step cited lines inside the node's code")
    ids = {n.id for n in nodes} - {node.id}
    return NodeExplain(steps=steps, input=_known(sub.input, ids), output=_known(sub.output, ids))


def call_links(node: Node, nodes: Sequence[Node], hops: Sequence[Hop]) -> tuple[CallLink, ...]:
    """Callees of the node's anchors. `node_id` is the deepest other node that holds the callee."""
    links: dict[str, str | None] = {}
    for h in _live(hops):
        if not any(anchors_overlap(h.caller, a) for a in node.anchors):
            continue
        holders = [
            n
            for n in nodes
            if n.id != node.id and any(anchor_contains(a, h.callee) for a in n.anchors)
        ]
        deepest = max(holders, key=lambda n: n.level, default=None)
        links.setdefault(h.callee.symbol, deepest.id if deepest else None)
    return tuple(CallLink(symbol=s, node_id=i) for s, i in links.items())
