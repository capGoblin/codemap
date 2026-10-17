import re
from collections.abc import Sequence

from codemap.domain.models import Anchor, Effect, Hop, Node

_PATH_KINDS = {"call", "async"}
_SIDE_KINDS = {"error", "branch"}


def anchor_key(a: Anchor) -> tuple[str, int, int, str]:
    """Identity of an anchor. Ignores content_hash, which not every anchor has."""
    return (a.file, a.start_line, a.end_line, a.symbol)


def callee_named_in(caller_text: str, callee_symbol: str) -> bool:
    name = callee_symbol.rsplit(".", 1)[-1]
    return re.search(rf"\b{re.escape(name)}\b", caller_text) is not None


def path_points(entry: Anchor, hops: Sequence[Hop]) -> list[Anchor]:
    children: dict[tuple[str, int, int, str], list[Anchor]] = {}
    for h in hops:
        if h.kind in _PATH_KINDS and h.verdict != "rejected":
            children.setdefault(anchor_key(h.caller), []).append(h.callee)
    seen: set[tuple[str, int, int, str]] = set()
    order: list[Anchor] = []

    def visit(a: Anchor) -> None:
        key = anchor_key(a)
        if key in seen:
            return
        seen.add(key)
        order.append(a)
        for child in children.get(key, []):
            visit(child)

    visit(entry)
    return order


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


def rollup_effects(children: Sequence[Node]) -> tuple[Effect, ...]:
    seen: set[tuple[object, ...]] = set()
    out: list[Effect] = []
    for child in children:
        for e in child.effects:
            key = (e.category, e.target, e.op, e.fields, anchor_key(e.anchor))
            if key not in seen:
                seen.add(key)
                out.append(e)
    return tuple(out)


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
