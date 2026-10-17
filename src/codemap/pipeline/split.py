"""Split the recorded path into phases (level 0) and steps (level 1).

The model proposes titles, spans and step anchors. Code sets phase anchors and all effects,
and drops step anchors that lie off the phase. Nothing here emits events or touches the store,
because `split_steps` runs on worker threads.
"""

import uuid
from collections.abc import Sequence

from pydantic import BaseModel, model_validator

from codemap.agents.limits import LimitReached
from codemap.agents.loop import run_tool_loop
from codemap.agents.model import ModelError
from codemap.domain.models import Anchor, Edge, EdgeKind, Effect, Hop, Node
from codemap.domain.rules import anchor_contains, assign_effects
from codemap.pipeline.context import TraceContext, prompt, read_tools
from codemap.repo.anchors import with_hash


class PhaseDraft(BaseModel):
    title: str
    does: str
    input: str
    output: str
    boundary_reason: str
    start: int
    end: int


class PhasesSubmit(BaseModel):
    """Spans must start at 0, touch end to start, and not overlap."""

    phases: list[PhaseDraft]

    @model_validator(mode="after")
    def _check_spans(self) -> "PhasesSubmit":
        expected = 0
        for i, p in enumerate(self.phases):
            if p.end < p.start:
                raise ValueError(f"phase {i}: end {p.end} is before start {p.start}")
            if p.start != expected:
                raise ValueError(f"phase {i}: start must be {expected}, got {p.start}")
            expected = p.end + 1
        return self


def _phases_schema(count: int) -> type[PhasesSubmit]:
    """A schema that also requires the spans to cover indexes 0..count-1."""

    class Covering(PhasesSubmit):
        @model_validator(mode="after")
        def _check_cover(self) -> "Covering":
            last = self.phases[-1].end if self.phases else -1
            if last != count - 1:
                raise ValueError(f"phases must cover indexes 0..{count - 1}; last end is {last}")
            return self

    return Covering


class StepDraft(BaseModel):
    title: str
    does: str
    input: str
    output: str
    boundary_reason: str
    anchors: list[Anchor]
    parallel_group: int | None = None


class StepsSubmit(BaseModel):
    steps: list[StepDraft]


def _new_id() -> str:
    return uuid.uuid4().hex


def _list_anchors(anchors: Sequence[Anchor]) -> str:
    return "\n".join(
        f"{i}: {a.file}:{a.start_line}-{a.end_line} {a.symbol}" for i, a in enumerate(anchors)
    )


def split_phases(
    ctx: TraceContext, question: str, points: list[Anchor], effects: list[Effect]
) -> tuple[list[Node], str | None]:
    """Return (phases, failure reason). The reason is set when a limit or model error stopped it."""
    if not points:
        return [], None
    user = f"Question: {question}\n\nPath points:\n{_list_anchors(points)}"
    try:
        sub = run_tool_loop(
            ctx.model,
            system=prompt("split_phases"),
            user=user,
            tools=[],
            submit_schema=_phases_schema(len(points)),
            budget=ctx.budget,
        )
    except (LimitReached, ModelError) as exc:
        return [], str(exc)
    phases = []
    for order, draft in enumerate(sub.phases):
        anchors = tuple(points[draft.start : draft.end + 1])
        phases.append(
            Node(
                id=_new_id(),
                level=0,
                parent_id=None,
                order=order,
                title=draft.title,
                does=draft.does,
                input=draft.input,
                output=draft.output,
                boundary_reason=draft.boundary_reason,
                anchors=anchors,
                effects=assign_effects(anchors, effects),
            )
        )
    return phases, None


def _inside(phase: Node, anchor: Anchor) -> bool:
    return any(anchor_contains(outer, anchor) for outer in phase.anchors)


def split_steps(
    ctx: TraceContext, phase: Node, effects: list[Effect]
) -> tuple[list[Node], str | None]:
    """Return (steps, failure reason). Safe to call from a worker thread."""
    user = (
        f"Phase: {phase.title}\n{phase.does}\nInput: {phase.input}\nOutput: {phase.output}\n\n"
        f"Phase anchors:\n{_list_anchors(phase.anchors)}"
    )
    try:
        sub = run_tool_loop(
            ctx.model,
            system=prompt("split_steps"),
            user=user,
            tools=read_tools(ctx.tools),
            submit_schema=StepsSubmit,
            budget=ctx.budget,
        )
    except (LimitReached, ModelError) as exc:
        return [], str(exc)
    steps: list[Node] = []
    for draft in sub.steps:
        kept = tuple(with_hash(ctx.tools, a) for a in draft.anchors if _inside(phase, a))
        if not kept:
            continue
        steps.append(
            Node(
                id=_new_id(),
                level=1,
                parent_id=phase.id,
                order=len(steps),
                title=draft.title,
                does=draft.does,
                input=draft.input,
                output=draft.output,
                boundary_reason=draft.boundary_reason,
                anchors=kept,
                effects=assign_effects(kept, effects),
                parallel_group=draft.parallel_group,
            )
        )
    return steps, None


def _layers(steps: Sequence[Node]) -> list[list[Node]]:
    """Group consecutive steps that share a parallel_group. Other steps stand alone."""
    layers: list[list[Node]] = []
    for step in steps:
        same = (
            layers
            and step.parallel_group is not None
            and layers[-1][0].parallel_group == step.parallel_group
        )
        if same:
            layers[-1].append(step)
        else:
            layers.append([step])
    return layers


def steps_edges(steps: list[Node]) -> list[Edge]:
    layers = _layers(steps)
    return [
        Edge(source_id=src.id, target_id=dst.id, kind="call")
        for before, after in zip(layers, layers[1:], strict=False)
        for src in before
        for dst in after
    ]


def phase_edges(phases: list[Node], hops: list[Hop]) -> list[Edge]:
    edges: list[Edge] = []
    for left, right in zip(phases, phases[1:], strict=False):
        crossing = [
            h
            for h in hops
            if h.kind in {"call", "async"}
            and h.verdict != "rejected"
            and _inside(left, h.caller)
            and _inside(right, h.callee)
        ]
        kind: EdgeKind = "async" if any(h.kind == "async" for h in crossing) else "call"
        edges.append(Edge(source_id=left.id, target_id=right.id, kind=kind))
    return edges


def _container(nodes: Sequence[Node], anchor: Anchor) -> Node | None:
    """The deepest node that holds the anchor."""
    holders = [n for n in nodes if _inside(n, anchor)]
    return max(holders, key=lambda n: n.level, default=None)


def side_nodes(side: list[Hop], nodes: list[Node]) -> tuple[list[Node], list[Edge]]:
    """One dimmed node per error or branch hop, tied to the node that holds its caller."""
    out: list[Node] = []
    edges: list[Edge] = []
    for h in side:
        holder = _container(nodes, h.caller)
        if holder is None:
            continue
        siblings = [
            n for n in [*nodes, *out] if n.level == holder.level and n.parent_id == holder.parent_id
        ]
        side_node = Node(
            id=_new_id(),
            level=holder.level,
            parent_id=holder.parent_id,
            order=len(siblings),
            title=h.callee.symbol,
            does=h.evidence,
            input="",
            output="",
            boundary_reason=f"{h.kind} path from {h.caller.symbol}",
            anchors=(h.callee,),
        )
        out.append(side_node)
        edges.append(Edge(source_id=holder.id, target_id=side_node.id, kind=h.kind))
    return out, edges
