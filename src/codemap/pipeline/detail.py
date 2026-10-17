"""Function detail for the UI side panel. Code only, no model."""

from collections.abc import Sequence

from codemap.domain.models import Anchor, FunctionDetail, Hop, Node
from codemap.domain.rules import anchor_key
from codemap.repo.sandbox import OutsideRepoError
from codemap.repo.tools import RepoTools


def _signature(tools: RepoTools, anchor: Anchor) -> str:
    if tools.index is None:
        return anchor.symbol
    containing = [
        s
        for s in tools.index.outline(anchor.file)
        if s.start_line <= anchor.start_line <= s.end_line
    ]
    if not containing:
        return anchor.symbol
    return min(containing, key=lambda s: s.end_line - s.start_line).signature


def _detail(tools: RepoTools, anchor: Anchor, hops: Sequence[Hop]) -> FunctionDetail:
    key = anchor_key(anchor)
    calls = tuple(h.callee.symbol for h in hops if anchor_key(h.caller) == key)
    try:
        lines = tools.file_text(anchor.file).splitlines()
    except (OSError, OutsideRepoError) as exc:
        return FunctionDetail(anchor=anchor, signature=f"unavailable: {exc}", code="", calls=calls)
    code = "\n".join(lines[anchor.start_line - 1 : anchor.end_line])
    return FunctionDetail(
        anchor=anchor, signature=_signature(tools, anchor), code=code, calls=calls
    )


def build_detail(tools: RepoTools, node: Node, hops: list[Hop]) -> list[FunctionDetail]:
    return [_detail(tools, a, hops) for a in node.anchors]
