import re
from collections.abc import Iterable, Sequence

from codemap.domain.models import Anchor, Effect, Hop, Node

_PATH_KINDS = {"call", "async"}
_SIDE_KINDS = {"error", "branch"}


def anchor_key(a: Anchor) -> tuple[str, int, int, str]:
    """Identity of an anchor. Ignores content_hash, which not every anchor has."""
    return (a.file, a.start_line, a.end_line, a.symbol)


def callee_named_in(caller_text: str, callee_symbol: str) -> bool:
    name = callee_symbol.rsplit(".", 1)[-1]
    return re.search(rf"\b{re.escape(name)}\b", caller_text) is not None


def anchors_overlap(a: Anchor, b: Anchor) -> bool:
    """Same file and the line ranges share a line. Symbol spelling is ignored on purpose."""
    return a.file == b.file and a.start_line <= b.end_line and b.start_line <= a.end_line


def path_points(entry: Anchor, hops: Sequence[Hop]) -> list[Anchor]:
    edges = [h for h in hops if h.kind in _PATH_KINDS and h.verdict != "rejected"]
    order: list[Anchor] = []

    def visit(a: Anchor) -> None:
        if any(anchors_overlap(a, seen) for seen in order):
            return
        order.append(a)
        for h in edges:
            if anchors_overlap(h.caller, a):
                visit(h.callee)

    visit(entry)
    return order


def unreachable_hops(points: Sequence[Anchor], hops: Sequence[Hop]) -> list[Hop]:
    """Path hops whose caller does not lie on the path. They are lost from the graph."""
    return [
        h
        for h in hops
        if h.kind in _PATH_KINDS
        and h.verdict != "rejected"
        and not any(anchors_overlap(h.caller, p) for p in points)
    ]


def side_hops(hops: Sequence[Hop]) -> list[Hop]:
    return [h for h in hops if h.kind in _SIDE_KINDS and h.verdict != "rejected"]


def anchor_contains(outer: Anchor, inner: Anchor) -> bool:
    return (
        outer.file == inner.file
        and outer.start_line <= inner.start_line
        and inner.end_line <= outer.end_line
    )


def assign_effects(anchors: Sequence[Anchor], effects: Sequence[Effect]) -> tuple[Effect, ...]:
    return tuple(e for e in effects if any(anchor_contains(a, e.anchor) for a in anchors))


def dedupe_effects(effects: Iterable[Effect]) -> tuple[Effect, ...]:
    seen: set[tuple[object, ...]] = set()
    out: list[Effect] = []
    for e in effects:
        key = (e.category, e.target, e.op, e.fields, anchor_key(e.anchor))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return tuple(out)


def rollup_effects(children: Sequence[Node]) -> tuple[Effect, ...]:
    return dedupe_effects(e for child in children for e in child.effects)


def uncovered_effects(phase: Node, children: Sequence[Node]) -> tuple[Effect, ...]:
    """The phase's own effects on lines that no step anchor covers."""
    return tuple(
        e
        for e in phase.effects
        if not any(anchor_contains(a, e.anchor) for c in children for a in c.anchors)
    )


def io_chain_warning(phase: Node, steps: Sequence[Node]) -> str | None:
    """Warn only when a step end has no input or output while the phase has one.

    Free-text descriptions rarely match word for word, so wording is not compared.
    """
    if not steps:
        return None
    problems = []
    if phase.input.strip() and not steps[0].input.strip():
        problems.append("first step has no input, but the phase has one")
    if phase.output.strip() and not steps[-1].output.strip():
        problems.append("last step has no output, but the phase has one")
    return "; ".join(problems) or None


def drop_ratio(kept: int, dropped: int) -> float:
    total = kept + dropped
    return dropped / total if total else 0.0
