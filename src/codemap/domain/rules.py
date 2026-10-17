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


def _norm(text: str) -> str:
    return text.strip().casefold()


def io_chain_warning(phase: Node, steps: Sequence[Node]) -> str | None:
    if not steps:
        return None
    problems = []
    if _norm(steps[0].input) != _norm(phase.input):
        problems.append(
            f"first step input {steps[0].input!r} differs from phase input {phase.input!r}"
        )
    if _norm(steps[-1].output) != _norm(phase.output):
        problems.append(
            f"last step output {steps[-1].output!r} differs from phase output {phase.output!r}"
        )
    return "; ".join(problems) or None


def drop_ratio(kept: int, dropped: int) -> float:
    total = kept + dropped
    return dropped / total if total else 0.0
