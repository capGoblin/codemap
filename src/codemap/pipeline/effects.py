"""One model call per phase: the effects inside its expanded code. Code checks every anchor."""

import re
from collections.abc import Sequence

from pydantic import BaseModel

from codemap.agents.limits import LimitReached
from codemap.agents.loop import run_tool_loop
from codemap.agents.model import ModelError
from codemap.agents.schema import tolerant_list
from codemap.domain.models import Anchor, Effect, EffectCategory
from codemap.domain.rules import anchor_contains, anchor_key, normalize_op, normalize_target
from codemap.pipeline.context import TraceContext, prompt
from codemap.pipeline.split import anchors_code
from codemap.repo.anchors import check_range, with_hash

EFFECTS_MAX_LINES = 1500
EFFECTS_HEAD_LINES = 30
EFFECTS_MAX_TURNS = 3
_IDENT = re.compile(r"[A-Za-z_]\w*")


class EffectDraft(BaseModel):
    category: EffectCategory
    target: str
    op: str
    fields: tuple[str, ...] = ()
    file: str
    line: int
    symbol: str = ""


class EffectsSubmit(BaseModel):
    effects: list[EffectDraft]

    _unwrap = tolerant_list("effects")


def _anchor_at(ctx: TraceContext, draft: EffectDraft, points: Sequence[Anchor]) -> Anchor | None:
    """A one-line anchor for the draft, or None when the line is outside every point."""
    here = Anchor(
        file=draft.file, start_line=max(draft.line, 1), end_line=max(draft.line, 1), symbol="x"
    )
    if not any(anchor_contains(p, here) for p in points) or check_range(ctx.tools, here):
        return None
    line = ctx.tools.file_text(draft.file).splitlines()[draft.line - 1]
    name = draft.symbol.rsplit(".", 1)[-1]
    if not name or re.search(rf"\b{re.escape(name)}\b", line) is None:
        idents = _IDENT.findall(line)
        if not idents:
            return None
        name = idents[0]
    return with_hash(ctx.tools, here.model_copy(update={"symbol": name}))


def _key(effect: Effect) -> tuple[object, ...]:
    return (effect.category, effect.target, effect.op, anchor_key(effect.anchor))


def phase_effects(
    ctx: TraceContext, phase_title: str, points: Sequence[Anchor], known: Sequence[Effect]
) -> tuple[list[Effect], str | None]:
    """Return (new effects already stored, failure reason).

    `points` are the phase anchors and the callees expanded under it. An effect whose line is
    not inside one of them is dropped, as is one already in `known`.
    """
    if not points:
        return [], None
    code = anchors_code(ctx.tools, points, EFFECTS_MAX_LINES, EFFECTS_HEAD_LINES)
    try:
        sub = run_tool_loop(
            ctx.model,
            system=prompt("phase_effects"),
            user=f"Stage: {phase_title}\n\nCode:\n{code}",
            tools=[],
            submit_schema=EffectsSubmit,
            budget=ctx.build_budget,
            max_turns=EFFECTS_MAX_TURNS,
        )
    except (LimitReached, ModelError) as exc:
        return [], str(exc)
    seen = {_key(e) for e in known}
    out: list[Effect] = []
    for draft in sub.effects:
        try:
            op = normalize_op(draft.op)
        except ValueError:
            continue
        anchor = _anchor_at(ctx, draft, points)
        if anchor is None:
            continue
        effect = Effect(
            category=draft.category,
            target=normalize_target(draft.category, draft.target),
            op=op,
            fields=draft.fields,
            anchor=anchor,
        )
        if _key(effect) in seen:
            continue
        seen.add(_key(effect))
        ctx.store.add_walk_effect(ctx.trace_id, effect)
        out.append(effect)
    return out, None
