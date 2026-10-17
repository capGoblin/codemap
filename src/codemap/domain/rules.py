import re
from collections.abc import Iterable, Sequence

from codemap.domain.models import Anchor, Bridge, Effect, EffectOp, Hop, Node

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


def ordered_points(entry: Anchor, hops: Sequence[Hop]) -> tuple[list[Anchor], list[Bridge]]:
    """Path points by DFS from the entry, then each unreached component in recorded order.

    A component is a group of unreached hops linked by overlapping anchors. Its root is the
    first recorded caller that is not a callee in the component. Each joined component adds a
    Bridge from the last point so far to its root, so no recorded hop is lost.
    """
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
    rest = [h for h in edges if not any(anchors_overlap(h.caller, p) for p in order)]
    bridges: list[Bridge] = []
    for comp in _components(rest):
        callees = [h.callee for h in comp]
        roots = [h.caller for h in comp if not any(anchors_overlap(h.caller, c) for c in callees)]
        root = (roots or [comp[0].caller])[0]
        if any(anchors_overlap(root, seen) for seen in order):
            continue
        bridges.append(Bridge(from_anchor=order[-1], to_anchor=root))
        visit(root)
    return order, bridges


def _components(hops: Sequence[Hop]) -> list[list[Hop]]:
    """Group hops whose anchors overlap, directly or through other hops. Recorded order."""
    comps: list[list[Hop]] = []
    for h in hops:
        linked = [
            c
            for c in comps
            if any(
                anchors_overlap(x, y)
                for k in c
                for x in (k.caller, k.callee)
                for y in (h.caller, h.callee)
            )
        ]
        merged = [h]
        for c in linked:
            merged = [*c, *merged]
            comps.remove(c)
        comps.append(sorted(merged, key=hops.index))
    return sorted(comps, key=lambda c: hops.index(c[0]))


def path_points(entry: Anchor, hops: Sequence[Hop]) -> list[Anchor]:
    return ordered_points(entry, hops)[0]


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


_OLD_WRITE_OPS = {"write", "delete", "publish"}
_OLD_READ_OPS = {"read", "consume", "call"}


def normalize_op(raw: str) -> EffectOp:
    """Map any current or v2 effect op to `read` or `write`."""
    op = raw.strip().lower()
    if op in _OLD_WRITE_OPS:
        return "write"
    if op in _OLD_READ_OPS:
        return "read"
    raise ValueError(f"unknown effect op: {raw!r}")


_FILLER_WORDS = {"row", "rows", "table", "tables"}
_GENERIC_STORES = {"s3", "gcs", "blob", "azure blob", "object store", "storage", "bucket"}
_STORE_SCHEME = re.compile(r"^(s3|gs|gcs|az|abfs)://", re.IGNORECASE)
_METHOD_SUFFIX = re.compile(r"\.\w+(\(\))?$")


def normalize_target(category: str, raw: str) -> str:
    """Reduce a model-written target to the real name. Keep the identifier, drop the filler."""
    text = raw.strip().strip("`'\"").strip()
    if " via " in text:
        left, right = text.split(" via ", 1)
        if left.strip().lower() in _GENERIC_STORES:
            text = _METHOD_SUFFIX.sub("", right.strip())
        else:
            text = left.strip()
    if category == "object_store":
        text = _STORE_SCHEME.sub("", text)
    words = [w.strip("`'\"").rstrip(".,;:") for w in text.split()]
    kept = [w for w in words if w and w.lower() not in _FILLER_WORDS]
    return " ".join(kept or words)
