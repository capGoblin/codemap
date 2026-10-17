"""Grounding checks (spec 5.3): drop claims that fail, roll up effects, warn on io chains."""

from collections.abc import Sequence
from dataclasses import dataclass

from codemap.domain.models import Anchor, Edge, Node
from codemap.domain.rules import anchor_contains, io_chain_warning, rollup_effects
from codemap.repo.anchors import check_anchor
from codemap.repo.tools import RepoTools

PARTIAL_DROP_RATIO = 0.3


@dataclass
class ValidationReport:
    nodes: list[Node]
    edges: list[Edge]
    warnings: list[str]
    dropped: int


def _on_path(node: Node, points: Sequence[Anchor]) -> bool:
    return any(anchor_contains(a, p) or anchor_contains(p, a) for a in node.anchors for p in points)


def _grounded(tools: RepoTools, node: Node) -> Node:
    """Keep only anchors and effects whose anchors pass `check_anchor`."""
    return node.model_copy(
        update={
            "anchors": tuple(a for a in node.anchors if check_anchor(tools, a) is None),
            "effects": tuple(e for e in node.effects if check_anchor(tools, e.anchor) is None),
        }
    )


def _keep(node: Node, points: Sequence[Anchor], side_ids: set[str] | frozenset[str]) -> bool:
    if not node.anchors:
        return False
    return node.id in side_ids or _on_path(node, points)


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
            n = n.model_copy(update={"effects": rollup_effects(children)})
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
    for node in nodes:
        checked = _grounded(tools, node)
        if _keep(checked, points, side_ids):
            kept.append(checked)
    alive = {n.id for n in kept}
    kept = [n for n in kept if n.parent_id is None or n.parent_id in alive]
    alive = {n.id for n in kept}
    warnings: list[str] = []
    kept = _rollup(kept, warnings)
    kept_edges = [e for e in edges if e.source_id in alive and e.target_id in alive]
    return ValidationReport(kept, kept_edges, warnings, len(nodes) - len(kept))
