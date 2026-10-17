"""Resolve a user question or a direct `path:Symbol` entry to ranked entry candidates."""

import re

from pydantic import BaseModel, Field

from codemap.agents.limits import LimitReached
from codemap.agents.loop import run_tool_loop
from codemap.domain.models import Anchor, EntryCandidate
from codemap.pipeline.context import TraceContext, prompt, read_tools
from codemap.repo.anchors import check_anchor, with_hash
from codemap.repo.index import Symbol

MAX_CANDIDATES = 5
_DIRECT = re.compile(r"^([\w./@+-]+\.\w+):([A-Za-z_$][\w$.]*)$")


class ResolveSubmit(BaseModel):
    candidates: list[EntryCandidate] = Field(max_length=MAX_CANDIDATES)


def parse_direct_entry(text: str) -> tuple[str, str] | None:
    """Split `path/to/file.ext:Symbol.name` into (path, symbol), or None."""
    match = _DIRECT.match(text.strip())
    return (match.group(1), match.group(2)) if match else None


def _contains(outer: Symbol, inner: Symbol) -> bool:
    return (
        outer is not inner
        and outer.start_line <= inner.start_line <= inner.end_line <= outer.end_line
    )


def _match_symbols(symbols: list[Symbol], dotted: str) -> list[Symbol]:
    """Match on the last part. The class part picks between several matches."""
    *owners, last = dotted.split(".")
    found = [s for s in symbols if s.name.rsplit(".", 1)[-1] == last]
    if len(found) > 1 and owners:
        parents = [s for s in symbols if s.name.rsplit(".", 1)[-1] == owners[-1]]
        inside = [s for s in found if any(_contains(p, s) for p in parents)]
        found = inside or found
    return found


def _direct_candidates(ctx: TraceContext, path: str, dotted: str) -> list[EntryCandidate]:
    index = ctx.tools.index
    symbols = index.outline(path) if index else []
    return [
        EntryCandidate(
            anchor=Anchor(file=path, start_line=s.start_line, end_line=s.end_line, symbol=dotted),
            label=dotted,
            reason="Direct entry given by the user.",
        )
        for s in _match_symbols(symbols, dotted)[:MAX_CANDIDATES]
    ]


def _validated(ctx: TraceContext, candidates: list[EntryCandidate]) -> list[EntryCandidate]:
    kept = []
    for cand in candidates:
        if check_anchor(ctx.tools, cand.anchor) is None:
            kept.append(cand.model_copy(update={"anchor": with_hash(ctx.tools, cand.anchor)}))
    return kept


def resolve_entry(ctx: TraceContext, question: str) -> list[EntryCandidate]:
    """Return validated entry candidates, best first. Empty when none survive.

    Returns `[]` when a run limit is hit. Raises `ModelError` when the model call fails,
    so the caller can tell a failed endpoint from "no entry point found".
    """
    if direct := parse_direct_entry(question):
        return _validated(ctx, _direct_candidates(ctx, *direct))
    try:
        answer = run_tool_loop(
            ctx.model,
            system=prompt("resolve"),
            user=question,
            tools=read_tools(ctx.tools),
            submit_schema=ResolveSubmit,
            budget=ctx.budget,
        )
    except LimitReached:
        return []
    return _validated(ctx, answer.candidates)
