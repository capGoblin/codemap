"""Independent hop verifier: a fresh agent checks one claim and never sees the walk."""

import hashlib
from typing import Literal

from pydantic import BaseModel

from codemap.agents.limits import LimitReached
from codemap.agents.loop import run_tool_loop
from codemap.agents.model import ModelError
from codemap.agents.schema import tolerant_list
from codemap.domain.models import Anchor, Hop, VerifierResult
from codemap.pipeline.context import TraceContext, prompt, read_tools
from codemap.repo.anchors import check_anchor, with_hash


class VerdictSubmit(BaseModel):
    verdict: Literal["confirmed", "unsure", "rejected"]
    evidence: str
    evidence_anchors: list[Anchor] = []
    suggested_callee: Anchor | None = None

    _unwrap = tolerant_list("evidence_anchors")


def _identity(anchor: Anchor | None) -> str:
    if anchor is None:
        return "-"
    return (
        f"{anchor.file}:{anchor.start_line}:{anchor.end_line}:{anchor.symbol}:{anchor.content_hash}"
    )


def verdict_key(hop: Hop) -> str:
    raw = "|".join([_identity(hop.caller), _identity(hop.callee), hop.kind, _identity(hop.wiring)])
    return hashlib.sha256(raw.encode()).hexdigest()


def _hashed(ctx: TraceContext, anchor: Anchor) -> Anchor:
    return anchor if anchor.content_hash else with_hash(ctx.tools, anchor)


def _fmt(anchor: Anchor) -> str:
    return f"{anchor.file}:{anchor.start_line}-{anchor.end_line} ({anchor.symbol})"


def _claim(hop: Hop) -> str:
    wiring = _fmt(hop.wiring) if hop.wiring else "none"
    return (
        f"Caller: {_fmt(hop.caller)}\n"
        f"Callee: {_fmt(hop.callee)}\n"
        f"Hop type: {hop.hop_type}\n"
        f"Kind: {hop.kind}\n"
        f"Wiring cited: {wiring}"
    )


def _apply_rule(ctx: TraceContext, sub: VerdictSubmit) -> VerifierResult:
    """Recall first: a rejection needs evidence text and a valid evidence anchor."""
    verdict = sub.verdict
    if verdict == "rejected":
        valid = [a for a in sub.evidence_anchors if check_anchor(ctx.tools, a) is None]
        if not sub.evidence.strip() or not valid:
            verdict = "unsure"
    suggested = sub.suggested_callee
    if suggested is not None and check_anchor(ctx.tools, suggested) is not None:
        suggested = None
    return VerifierResult(verdict=verdict, evidence=sub.evidence, suggested_callee=suggested)


def verify_hop(ctx: TraceContext, hop: Hop) -> VerifierResult:
    hop = hop.model_copy(
        update={"caller": _hashed(ctx, hop.caller), "callee": _hashed(ctx, hop.callee)}
    )
    key = verdict_key(hop)
    cached = ctx.verdicts.get(key)
    if cached is not None:
        return cached
    try:
        sub = run_tool_loop(
            ctx.model,
            system=prompt("verify"),
            user=_claim(hop),
            tools=read_tools(ctx.tools),
            submit_schema=VerdictSubmit,
            budget=ctx.budget,
        )
    except (LimitReached, ModelError) as exc:
        return VerifierResult(verdict="unsure", evidence=f"verifier unavailable: {exc}")
    result = _apply_rule(ctx, sub)
    ctx.verdicts.put(key, result)
    return result
