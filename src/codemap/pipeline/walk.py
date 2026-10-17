"""Trace agent: walks the real call path from the entry point and records hops and effects."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, field_validator

from codemap.agents.limits import LimitReached
from codemap.agents.loop import Tool, run_tool_loop
from codemap.agents.model import ModelError
from codemap.domain.events import Event, EventKind
from codemap.domain.models import (
    Anchor,
    EdgeKind,
    Effect,
    EffectCategory,
    Hop,
    HopType,
    Node,
)
from codemap.domain.rules import (
    anchor_contains,
    callee_named_in,
    normalize_op,
    normalize_target,
)
from codemap.pipeline.context import TraceContext, prompt, read_tools
from codemap.pipeline.verify import verify_hop
from codemap.repo.anchors import check_anchor, with_hash
from codemap.repo.tools import RepoTools

KEEP_RECENT_TURNS = 12
HOP_LIMIT_TEXT = "hop limit reached; call submit"


class HopInput(BaseModel):
    caller: Anchor
    callee: Anchor
    kind: EdgeKind
    hop_type: HopType
    wiring: Anchor | None = None


class EffectInput(BaseModel):
    """Lenient input: any old or new op string. Stored as read or write."""

    category: EffectCategory
    target: str
    op: str
    fields: tuple[str, ...] = ()
    anchor: Anchor

    @field_validator("op")
    @classmethod
    def _known_op(cls, value: str) -> str:
        normalize_op(value)
        return value


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
    def __init__(
        self,
        ctx: TraceContext,
        budget: int,
        scope: list[Anchor] | None = None,
        scope_title: str = "",
    ) -> None:
        self.ctx = ctx
        self.hop_budget = budget
        self.scope = scope  # None means no scope check (skeleton pass)
        self.scope_title = scope_title
        self.hops: list[Hop] = []
        self.effects: list[Effect] = []
        self.hop_limited = False

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

    def _in_scope(self, caller: Anchor) -> bool:
        """Inside a phase anchor, or inside the callee of a hop already recorded in this pass."""
        if self.scope is None:
            return True
        allowed = [*self.scope, *(h.callee for h in self.hops)]
        return any(anchor_contains(outer, caller) for outer in allowed)

    def _caller_text(self, caller: Anchor) -> str:
        lines = self.ctx.tools.file_text(caller.file).splitlines()
        return "\n".join(lines[caller.start_line - 1 : caller.end_line])

    def record_hop(self, args: dict[str, Any]) -> str:
        if len(self.hops) >= self.hop_budget:
            self.hop_limited = True
            return HOP_LIMIT_TEXT
        spec = HopInput.model_validate(args)
        if error := self._first_error(spec.caller, spec.callee):
            return f"error: {error}"
        if not self._in_scope(spec.caller):
            return f"error: outside this phase; record only calls inside {self.scope_title}"
        tools = self.ctx.tools
        if spec.wiring is not None and self._first_error(spec.wiring):
            # A bad wiring anchor must not lose a real hop (spec 5.4). The verifier decides.
            spec = spec.model_copy(update={"wiring": None, "hop_type": "indirect"})
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
        self.ctx.store.add_hop(self.ctx.trace_id, hop)  # saved now so a crash keeps it
        self.emit("hop_found", f"{_fmt(hop.caller)} -> {_fmt(hop.callee)}", hop_id=hop.id)
        if verdict is not None:
            self.emit("hop_verified", f"{hop.id}: {verdict}", hop_id=hop.id, verdict=verdict)

    def record_effect(self, args: dict[str, Any]) -> str:
        spec = EffectInput.model_validate(args)
        if error := self._first_error(spec.anchor):
            return f"error: {error}"
        anchor = with_hash(self.ctx.tools, spec.anchor)
        effect = Effect(
            category=spec.category,
            target=normalize_target(spec.category, spec.target),
            op=normalize_op(spec.op),
            fields=spec.fields,
            anchor=anchor,
        )
        self.effects.append(effect)
        self.ctx.store.add_walk_effect(self.ctx.trace_id, effect)
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


def _user_message(ctx: TraceContext, entry: Anchor, question: str, budget: int) -> str:
    return f"Question: {question}\nEntry point: {_fmt(entry)}\nHop limit: {budget}"


def _deepen_message(phase: Node, question: str, budget: int, known: list[Hop]) -> str:
    anchors = "\n".join(_fmt(a) for a in phase.anchors)
    seen = "\n".join(f"{_fmt(h.caller)} -> {_fmt(h.callee)}" for h in known) or "none"
    return (
        f"Question: {question}\nPhase: {phase.title}\nAnchors:\n{anchors}\n"
        f"Hops already known under this phase:\n{seen}\nHop limit: {budget}\n"
        "Go into the functions that do the real work of this stage."
    )


def _run(walker: _Walker, system: str, user: str) -> WalkResult:
    ctx = walker.ctx
    partial: str | None = None
    try:
        done = run_tool_loop(
            ctx.model,
            system=system,
            user=user,
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
    if partial is None and walker.hop_limited:
        partial = "hop limit reached"
    return WalkResult(walker.hops, walker.effects, partial)


def walk_skeleton(ctx: TraceContext, entry: Anchor, question: str) -> WalkResult:
    budget = ctx.settings.skeleton_hops
    walker = _Walker(ctx, budget)
    return _run(walker, prompt("walk_skeleton"), _user_message(ctx, entry, question, budget))


def walk_deepen(
    ctx: TraceContext, phase: Node, question: str, budget: int, known: list[Hop]
) -> WalkResult:
    walker = _Walker(ctx, budget, list(phase.anchors), phase.title)
    return _run(walker, prompt("walk_deepen"), _deepen_message(phase, question, budget, known))


def deepen_budgets(
    phases: list[Node], tools: RepoTools, total: int, floor: int = 5
) -> dict[str, int]:
    """Split `total` hops across phases by anchored lines. Every phase gets at least `floor`."""
    weights = {p.id: sum(a.end_line - a.start_line + 1 for a in p.anchors) for p in phases}
    weight_sum = sum(weights.values()) or 1
    return {pid: max(floor, round(total * w / weight_sum)) for pid, w in weights.items()}


def walk_path(ctx: TraceContext, entry: Anchor, question: str) -> WalkResult:
    """Single-pass walk kept for run.py until it uses the two passes."""
    budget = ctx.settings.max_hops
    walker = _Walker(ctx, budget)
    return _run(walker, prompt("walk_skeleton"), _user_message(ctx, entry, question, budget))
