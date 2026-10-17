"""Static call expansion: follow call sites inside a phase down to their in-repo definitions.

This replaces the LLM deepen walk. It costs no tokens. Every hop it records is a direct call
whose callee name is in the caller's code, so its verdict is `code_checked`.
"""

import re
import uuid

from codemap.domain.models import Anchor, Hop, Node
from codemap.domain.rules import anchor_key
from codemap.pipeline.context import TraceContext
from codemap.pipeline.walk import WalkResult, _Walker
from codemap.repo.anchors import with_hash
from codemap.repo.calls import COMMON_METHODS, CallSite, calls_in
from codemap.repo.index import Symbol

IMPORT_LINES = 80
Candidate = tuple[str, Symbol]


def _dir_distance(a: str, b: str) -> int:
    left, right = a.split("/")[:-1], b.split("/")[:-1]
    common = 0
    for x, y in zip(left, right, strict=False):
        if x != y:
            break
        common += 1
    return len(left) + len(right) - 2 * common


def _imports(ctx: TraceContext, file: str) -> list[str]:
    try:
        lines = ctx.tools.file_text(file).splitlines()[:IMPORT_LINES]
    except OSError:
        return []
    return [ln for ln in lines if re.search(r"\b(import|require|use|using|include|from)\b", ln)]


def _imported(path: str, import_lines: list[str]) -> bool:
    """The file's module path, or its name, appears in an import line of the caller."""
    stem = path.rsplit(".", 1)[0]
    name = stem.rsplit("/", 1)[-1]
    dotted = stem.replace("/", ".")
    for line in import_lines:
        if dotted in line or stem in line or re.search(rf"\b{re.escape(name)}\b", line):
            return True
    return False


def _unique_nearest(caller_file: str, found: list[Candidate]) -> list[Candidate]:
    """The candidates in the nearest directory, or none when two files tie."""
    best = min(_dir_distance(caller_file, p) for p, _ in found)
    near = [c for c in found if _dir_distance(caller_file, c[0]) == best]
    return near if len({p for p, _ in near}) == 1 else []


def pick_definition(
    ctx: TraceContext, caller_file: str, site: CallSite, found: list[Candidate]
) -> Candidate | None:
    """Choose one definition: same file, then imported file, then nearest path. Else None."""
    dotted = "." in site.full or "->" in site.full or "::" in site.full
    needs_proof = dotted and site.name in COMMON_METHODS
    if not found:
        return None
    same = [c for c in found if c[0] == caller_file]
    imported = [c for c in found if _imported(c[0], _imports(ctx, caller_file))]
    if len(found) == 1 and not needs_proof:
        pool = found
    elif same:
        pool = same
    elif imported:
        pool = imported
    elif needs_proof:
        return None
    else:
        pool = _unique_nearest(caller_file, found)
    return pool[0] if len(pool) == 1 else None


def _size(anchor: Anchor) -> int:
    return anchor.end_line - anchor.start_line


def expand_static(
    ctx: TraceContext,
    phase: Node,
    known: list[Hop],
    max_depth: int = 3,
    max_points: int = 80,
) -> WalkResult:
    """BFS over call sites from the phase anchors. Up to `max_points` new callee anchors."""
    walker = _Walker(ctx, max_points, list(phase.anchors), phase.title)
    visited = {anchor_key(a) for a in phase.anchors}
    recorded = {(anchor_key(h.caller), anchor_key(h.callee)) for h in known}
    foreign = {anchor_key(h.callee) for h in known}  # known callees belong to other stages
    resolved: dict[tuple[str, str], Candidate | None] = {}
    frontier = list(phase.anchors)
    for _ in range(max_depth):
        if not frontier or ctx.cancel.is_set():
            break
        found: dict[tuple[str, int, int, str], tuple[Anchor, Anchor]] = {}
        for caller in frontier:
            for site in calls_in(ctx.tools, caller):
                key = (caller.file, site.full or site.name)
                if key not in resolved:
                    hits = ctx.tools.index.find_definition(site.name) if ctx.tools.index else []
                    resolved[key] = pick_definition(ctx, caller.file, site, hits)
                pick = resolved[key]
                if pick is None:
                    continue
                path, sym = pick
                callee = Anchor(
                    file=path, start_line=sym.start_line, end_line=sym.end_line, symbol=sym.name
                )
                ckey = anchor_key(callee)
                if ckey in visited or ckey in foreign or ckey in found:
                    continue
                if (anchor_key(caller), ckey) in recorded:
                    continue
                found[ckey] = (caller, callee)
        room = max_points - len(walker.hops)
        chosen = sorted(found.values(), key=lambda pair: _size(pair[1]), reverse=True)[:room]
        frontier = []
        for caller, callee in chosen:
            visited.add(anchor_key(callee))
            hop = Hop(
                id=uuid.uuid4().hex,
                caller=with_hash(ctx.tools, caller),
                callee=with_hash(ctx.tools, callee),
                kind="call",
                hop_type="direct",
                verdict="code_checked",
            )
            walker.store(hop)
            frontier.append(callee)
        if len(walker.hops) >= max_points:
            break
    return WalkResult(walker.hops, [], None)
