"""Grounding checks (spec 5.3): drop claims that fail, roll up effects, warn on io chains."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from codemap.domain.models import Anchor, Edge, Node
from codemap.domain.rules import (
    anchor_contains,
    dedupe_effects,
    io_chain_warning,
    rollup_effects,
    uncovered_effects,
)
from codemap.repo.anchors import check_anchor, check_range
from codemap.repo.tools import RepoTools

PARTIAL_DROP_RATIO = 0.3


@dataclass
class ValidationReport:
    nodes: list[Node]
    edges: list[Edge]
    warnings: list[str]
    dropped: int
    drops: list[str] = field(default_factory=list)


def _on_path(node: Node, points: Sequence[Anchor]) -> bool:
    return any(anchor_contains(a, p) or anchor_contains(p, a) for a in node.anchors for p in points)


def _fmt(a: Anchor) -> str:
    return f"{a.file}:{a.start_line}-{a.end_line} {a.symbol}"


def _grounded(tools: RepoTools, node: Node, parent: Node | None = None) -> tuple[Node, list[str]]:
    """Keep only anchors and effects whose anchors pass `check_anchor`.

    A step anchor inside one of its phase's anchors is a sub-range of a function the walk
    recorded. Its symbol is the enclosing function, which may not appear in the sub-range,
    so only the range is checked. Also return one message per rejected anchor.
    """
    problems: list[str] = []
    anchors: list[Anchor] = []
    for a in node.anchors:
        sub_range = parent is not None and any(anchor_contains(p, a) for p in parent.anchors)
        problem = check_range(tools, a) if sub_range else check_anchor(tools, a)
        if problem is None:
            anchors.append(a)
        else:
            problems.append(f"bad anchor {_fmt(a)}: {problem}")
    effects = tuple(e for e in node.effects if check_anchor(tools, e.anchor) is None)
    return node.model_copy(update={"anchors": tuple(anchors), "effects": effects}), problems


def _drop_reason(
    node: Node, problems: list[str], points: Sequence[Anchor], side_ids: set[str] | frozenset[str]
) -> str | None:
    """Why the node must go, or None to keep it."""
    if not node.anchors:
        return "; ".join(problems) or "no anchors"
    if node.id in side_ids or _on_path(node, points):
        return None
    return "not on the recorded path: " + ", ".join(_fmt(a) for a in node.anchors)


def _add_warning(node: Node, text: str, warnings: list[str]) -> Node:
    warnings.append(f"{node.title}: {text}")
    return node.model_copy(update={"warnings": (*node.warnings, text)})


def _rollup(nodes: list[Node], warnings: list[str]) -> list[Node]:
    steps: dict[str, list[Node]] = {}
    for n in nodes:
        if n.level == 1 and n.parent_id:
            steps.setdefault(n.parent_id, []).append(n)
    out: list[Node] = []
    for n in nodes:
        children = sorted(steps.get(n.id, []), key=lambda s: s.order)
        if n.level == 0 and children:
            # Steps may cover only part of the phase. Keep effects on the lines they skip.
            effects = dedupe_effects((*rollup_effects(children), *uncovered_effects(n, children)))
            n = n.model_copy(update={"effects": effects})
            if (problem := io_chain_warning(n, children)) is not None:
                n = _add_warning(n, problem, warnings)
        out.append(n)
    return out


def validate_graph(
    tools: RepoTools,
    nodes: list[Node],
    edges: list[Edge],
    points: list[Anchor],
    side_ids: set[str] | frozenset[str] = frozenset(),
) -> ValidationReport:
    kept: list[Node] = []
    drops: list[str] = []
    by_id = {n.id: n for n in nodes}
    for node in nodes:
        checked, problems = _grounded(tools, node, by_id.get(node.parent_id or ""))
        if (why := _drop_reason(checked, problems, points, side_ids)) is None:
            kept.append(checked)
        else:
            drops.append(f"dropped L{node.level} {node.title!r}: {why}")
    alive = {n.id for n in kept}
    orphans = [n for n in kept if n.parent_id is not None and n.parent_id not in alive]
    drops.extend(f"dropped L{n.level} {n.title!r}: parent was dropped" for n in orphans)
    kept = [n for n in kept if n.parent_id is None or n.parent_id in alive]
    alive = {n.id for n in kept}
    warnings: list[str] = []
    kept = _rollup(kept, warnings)
    kept_edges = [e for e in edges if e.source_id in alive and e.target_id in alive]
    return ValidationReport(kept, kept_edges, warnings, len(nodes) - len(kept), drops)
