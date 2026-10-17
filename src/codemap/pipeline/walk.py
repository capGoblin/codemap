"""Trace agent: walks the real call path from the entry point and records hops and effects."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from codemap.agents.limits import LimitReached
from codemap.agents.loop import Tool, run_tool_loop
from codemap.agents.model import ModelError
from codemap.domain.events import Event, EventKind
from codemap.domain.models import Anchor, EdgeKind, Effect, Hop, HopType
from codemap.domain.rules import callee_named_in
from codemap.pipeline.context import TraceContext, prompt, read_tools
from codemap.pipeline.verify import verify_hop
from codemap.repo.anchors import check_anchor, with_hash

KEEP_RECENT_TURNS = 12
HOP_LIMIT_TEXT = "hop limit reached; call submit"


class HopInput(BaseModel):
    caller: Anchor
    callee: Anchor
    kind: EdgeKind
    hop_type: HopType
    wiring: Anchor | None = None


class EffectInput(Effect):
    pass


class WalkSubmit(BaseModel):
    done: bool
    notes: str = ""


@dataclass
class WalkResult:
    hops: list[Hop]
    effects: list[Effect]
    partial_reason: str | None


def _fmt(anchor: Anchor) -> str:
    return f"{anchor.file}:{anchor.start_line}-{anchor.end_line} {anchor.symbol}"


class _Walker:
    def __init__(self, ctx: TraceContext) -> None:
        self.ctx = ctx
        self.hops: list[Hop] = []
        self.effects: list[Effect] = []

    def emit(self, kind: EventKind, message: str, **data: object) -> None:
        self.ctx.emit(
            Event(
                trace_id=self.ctx.trace_id,
                kind=kind,
                message=message,
                data=data,
                at=datetime.now(UTC),
            )
        )

    def _first_error(self, *anchors: Anchor | None) -> str | None:
        for anchor in anchors:
            if anchor is not None and (error := check_anchor(self.ctx.tools, anchor)):
                return error
        return None

    def _caller_text(self, caller: Anchor) -> str:
        lines = self.ctx.tools.file_text(caller.file).splitlines()
        return "\n".join(lines[caller.start_line - 1 : caller.end_line])

    def record_hop(self, args: dict[str, Any]) -> str:
        if len(self.hops) >= self.ctx.settings.max_hops:
            return HOP_LIMIT_TEXT
        spec = HopInput.model_validate(args)
        if error := self._first_error(spec.caller, spec.callee, spec.wiring):
            return f"error: {error}"
        tools = self.ctx.tools
        hop = Hop(
            id=uuid.uuid4().hex,
            caller=with_hash(tools, spec.caller),
            callee=with_hash(tools, spec.callee),
            kind=spec.kind,
            hop_type=spec.hop_type,
            wiring=with_hash(tools, spec.wiring) if spec.wiring else None,
        )
        if hop.hop_type == "direct" and callee_named_in(
            self._caller_text(hop.caller), hop.callee.symbol
        ):
            hop = hop.model_copy(update={"verdict": "code_checked"})
            self._store(hop)
            return "recorded"
        hop = hop.model_copy(update={"hop_type": "indirect"})
        result = verify_hop(self.ctx, hop)
        hop = hop.model_copy(update={"verdict": result.verdict, "evidence": result.evidence})
        self._store(hop, verdict=result.verdict)
        if result.verdict != "rejected":
            return "recorded"
        suggested = _fmt(result.suggested_callee) if result.suggested_callee else "none"
        return f"rejected: {result.evidence}; suggested callee: {suggested}"

    def _store(self, hop: Hop, verdict: str | None = None) -> None:
        self.hops.append(hop)
        self.emit("hop_found", f"{_fmt(hop.caller)} -> {_fmt(hop.callee)}", hop_id=hop.id)
        if verdict is not None:
            self.emit("hop_verified", f"{hop.id}: {verdict}", hop_id=hop.id, verdict=verdict)

    def record_effect(self, args: dict[str, Any]) -> str:
        spec = EffectInput.model_validate(args)
        if error := self._first_error(spec.anchor):
            return f"error: {error}"
        anchor = with_hash(self.ctx.tools, spec.anchor)
        self.effects.append(Effect(**{**spec.model_dump(), "anchor": anchor}))
        return "recorded"


def _walk_tools(walker: _Walker) -> list[Tool]:
    return [
        *read_tools(walker.ctx.tools),
        Tool(
            "record_hop",
            "Record one call from a caller function to a callee function.",
            HopInput.model_json_schema(),
            walker.record_hop,
        ),
        Tool(
            "record_effect",
            "Record one side effect with the anchor of the line that does it.",
            EffectInput.model_json_schema(),
            walker.record_effect,
        ),
    ]


def _user_message(ctx: TraceContext, entry: Anchor, question: str) -> str:
    return f"Question: {question}\nEntry point: {_fmt(entry)}\nHop limit: {ctx.settings.max_hops}"


def walk_path(ctx: TraceContext, entry: Anchor, question: str) -> WalkResult:
    walker = _Walker(ctx)
    partial: str | None = None
    try:
        done = run_tool_loop(
            ctx.model,
            system=prompt("walk"),
            user=_user_message(ctx, entry, question),
            tools=_walk_tools(walker),
            submit_schema=WalkSubmit,
            budget=ctx.budget,
            max_turns=ctx.settings.max_tool_calls,
            keep_recent_turns=KEEP_RECENT_TURNS,
        )
        if not done.done:
            partial = f"walk stopped early: {done.notes}"
    except LimitReached as exc:
        partial = f"limit reached: {exc.reason}"
    except ModelError as exc:
        partial = f"model error: {exc}"
    return WalkResult(walker.hops, walker.effects, partial)
