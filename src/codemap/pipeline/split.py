"""Split the recorded path into phases (level 0) and children of any node (level 1, 2, ...).

The model proposes titles, summaries, spans and child anchors. Code sets phase anchors and all
effects, and drops child anchors that lie off the parent. Nothing here emits events or touches
the store, because `split_children` runs on worker threads.
"""

import re
import uuid
from collections.abc import Collection, Sequence

from pydantic import BaseModel, model_validator

from codemap.agents.limits import LimitReached
from codemap.agents.loop import run_tool_loop
from codemap.agents.model import ModelError
from codemap.agents.schema import tolerant_list
from codemap.domain.models import Anchor, Edge, EdgeKind, Effect, Hop, Node
from codemap.domain.rules import anchor_contains, assign_effects
from codemap.pipeline.context import TraceContext, prompt
from codemap.repo.anchors import with_hash
from codemap.repo.tools import RepoTools

MAX_TITLE_WORDS = 4
MAX_SUMMARY_WORDS = 14
MAX_PHASES = 7


def _words(text: str) -> int:
    """Word count by whitespace. A trailing parenthesised code name does not count."""
    return len(re.sub(r"\([^)]*\)", " ", text).split())


def _check_lengths(title: str, summary: str) -> None:
    if _words(title) > MAX_TITLE_WORDS:
        raise ValueError(f"title {title!r} has more than {MAX_TITLE_WORDS} words")
    if _words(summary) > MAX_SUMMARY_WORDS:
        raise ValueError(f"summary has more than {MAX_SUMMARY_WORDS} words: {summary!r}")


class PhaseDraft(BaseModel):
    title: str
    summary: str = ""
    does: str
    input: str
    output: str
    boundary_reason: str
    start: int
    end: int

    @model_validator(mode="after")
    def _check_words(self) -> "PhaseDraft":
        _check_lengths(self.title, self.summary)
        return self


class PhasesSubmit(BaseModel):
    """Spans must start at 0, touch end to start, and not overlap."""

    phases: list[PhaseDraft]

    _unwrap = tolerant_list("phases")

    @model_validator(mode="after")
    def _check_spans(self) -> "PhasesSubmit":
        if not 1 <= len(self.phases) <= MAX_PHASES:
            raise ValueError(
                f"give 1 to {MAX_PHASES} phases, not {len(self.phases)}. "
                "Fold plumbing (auth, validation, idempotency, outbox, job runner, status "
                "updates) into the phase it serves."
            )
        expected = 0
        for i, p in enumerate(self.phases):
            if p.end < p.start:
                raise ValueError(f"phase {i}: end {p.end} is before start {p.start}")
            if p.start != expected:
                raise ValueError(f"phase {i}: start must be {expected}, got {p.start}")
            expected = p.end + 1
        return self


def _bare_name(title: str, symbols: Collection[str]) -> str | None:
    """The symbol when `title` is nothing but that symbol (or its last dotted part)."""
    norm = title.strip().casefold()
    for symbol in symbols:
        last = symbol.rsplit(".", 1)[-1].casefold()
        if norm in {symbol.casefold(), last, last.replace("_", " ")}:
            return symbol
    return None


def _title_rule(kind: str, index: int, title: str, symbols: Collection[str]) -> str | None:
    if (symbol := _bare_name(title, symbols)) is None:
        return None
    return (
        f"{kind} {index}: title {title!r} is only the function name {symbol!r}. "
        f"Rule: a title says what the {kind} does in at most {MAX_TITLE_WORDS} words, "
        f"for example 'Recall memories'. The code name goes in the details, not the title."
    )


def _phases_schema(points: Sequence[Anchor]) -> type[PhasesSubmit]:
    """A schema that also requires the spans to cover the points and titles to be real."""
    count = len(points)
    symbols = {a.symbol for a in points}

    class Covering(PhasesSubmit):
        @model_validator(mode="after")
        def _check_cover(self) -> "Covering":
            last = self.phases[-1].end if self.phases else -1
            if last != count - 1:
                raise ValueError(f"phases must cover indexes 0..{count - 1}; last end is {last}")
            return self

        @model_validator(mode="after")
        def _check_titles(self) -> "Covering":
            for i, p in enumerate(self.phases):
                if (problem := _title_rule("phase", i, p.title, symbols)) is not None:
                    raise ValueError(problem)
            return self

    return Covering


class ChildDraft(BaseModel):
    title: str
    summary: str = ""
    does: str
    input: str
    output: str
    boundary_reason: str
    anchors: list[Anchor]
    parallel_group: int | None = None

    _unwrap = tolerant_list("anchors")

    @model_validator(mode="after")
    def _check_words(self) -> "ChildDraft":
        _check_lengths(self.title, self.summary)
        return self


class ChildrenSubmit(BaseModel):
    steps: list[ChildDraft]

    _unwrap = tolerant_list("steps")


def _children_schema(parent: Node) -> type[ChildrenSubmit]:
    """A schema that also rejects a child title that is only a function name."""
    symbols = {a.symbol for a in parent.anchors}

    class Titled(ChildrenSubmit):
        @model_validator(mode="after")
        def _check_titles(self) -> "Titled":
            for i, child in enumerate(self.steps):
                names = symbols | {a.symbol for a in child.anchors}
                if (problem := _title_rule("step", i, child.title, names)) is not None:
                    raise ValueError(problem)
            return self

    return Titled


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
            submit_schema=_phases_schema(points),
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
                summary=draft.summary,
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


MAX_CODE_LINES = 800
HEAD_LINES = 40
STEP_MAX_TURNS = 4


def _numbered(lines: list[str], first: int) -> str:
    return "\n".join(f"{n}: {line}" for n, line in enumerate(lines, start=first))


def _anchor_lines(tools: RepoTools, anchor: Anchor) -> list[str]:
    try:
        return tools.file_text(anchor.file).splitlines()[anchor.start_line - 1 : anchor.end_line]
    except OSError:
        return []


def _signatures(tools: RepoTools, anchor: Anchor) -> str:
    """Outline rows of the file that lie inside the anchor range."""
    rows = [
        row
        for row in tools.outline(anchor.file).splitlines()
        if (m := re.match(r".+?:(\d+)-(\d+) ", row))
        and anchor.start_line <= int(m[1])
        and int(m[2]) <= anchor.end_line
    ]
    return "\n".join(rows)


def phase_code(tools: RepoTools, phase: Node) -> str:
    """The phase's anchored code, numbered by file line.

    Above MAX_CODE_LINES in total, send signatures and the first HEAD_LINES of each anchor.
    """
    bodies = [(a, _anchor_lines(tools, a)) for a in phase.anchors]
    small = sum(len(lines) for _, lines in bodies) <= MAX_CODE_LINES
    blocks: list[str] = []
    for anchor, lines in bodies:
        head = f"## {anchor.file}:{anchor.start_line}-{anchor.end_line} {anchor.symbol}"
        if small:
            blocks.append(f"{head}\n{_numbered(lines, anchor.start_line)}")
            continue
        shown = _numbered(lines[:HEAD_LINES], anchor.start_line)
        cut = f"[first {HEAD_LINES} of {len(lines)} lines; signatures below]"
        blocks.append(f"{head}\n{cut}\n{shown}\n{_signatures(tools, anchor)}".rstrip())
    return "\n\n".join(blocks)


def subpath_points(node: Node, hops: Sequence[Hop]) -> list[Anchor]:
    """Path points whose anchors lie inside the node's anchors, in first-seen order.

    A hop's caller and callee are both points. Rejected hops are skipped.
    """
    points: list[Anchor] = []
    for h in hops:
        if h.verdict == "rejected":
            continue
        for anchor in (h.caller, h.callee):
            if _inside(node, anchor) and anchor not in points:
                points.append(anchor)
    return points


def split_children(
    ctx: TraceContext, parent: Node, points: list[Anchor], effects: list[Effect]
) -> tuple[list[Node], str | None]:
    """Return (children at parent.level + 1, failure reason). Safe on a worker thread."""
    kind = "Phase" if parent.level == 0 else "Step"
    user = (
        f"{kind}: {parent.title}\n{parent.summary}\n{parent.does}\n"
        f"Input: {parent.input}\nOutput: {parent.output}\n\n"
        f"Parent anchors:\n{_list_anchors(parent.anchors)}\n\n"
        f"Sub-path points:\n{_list_anchors(points)}\n\n"
        f"Parent code:\n{phase_code(ctx.tools, parent)}"
    )
    try:
        sub = run_tool_loop(
            ctx.model,
            system=prompt("split_steps"),
            user=user,
            tools=[],
            submit_schema=_children_schema(parent),
            budget=ctx.budget,
            max_turns=STEP_MAX_TURNS,
        )
    except (LimitReached, ModelError) as exc:
        return [], str(exc)
    children: list[Node] = []
    for draft in sub.steps:
        kept = tuple(with_hash(ctx.tools, a) for a in draft.anchors if _inside(parent, a))
        if not kept:
            continue
        children.append(
            Node(
                id=_new_id(),
                level=parent.level + 1,
                parent_id=parent.id,
                order=len(children),
                title=draft.title,
                summary=draft.summary,
                does=draft.does,
                input=draft.input,
                output=draft.output,
                boundary_reason=draft.boundary_reason,
                anchors=kept,
                effects=assign_effects(kept, effects),
                parallel_group=draft.parallel_group,
            )
        )
    return children, None


def split_steps(
    ctx: TraceContext, phase: Node, effects: list[Effect]
) -> tuple[list[Node], str | None]:
    """Thin wrapper until run.py passes real sub-path points."""
    return split_children(ctx, phase, list(phase.anchors), effects)


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
