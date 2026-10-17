import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codemap.agents.model import ModelError
from codemap.domain.events import Event
from codemap.domain.models import Anchor, Node, Trace
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.walk import deepen_budgets, walk_deepen, walk_path, walk_skeleton
from codemap.settings import Settings
from fakes import ScriptedModel, resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"

UPLOAD = {"file": "app/api.py", "start_line": 5, "end_line": 8, "symbol": "upload"}
ACCEPT = {"file": "app/documents.py", "start_line": 12, "end_line": 14, "symbol": "accept_document"}
ENQUEUE = {"file": "app/queue.py", "start_line": 6, "end_line": 7, "symbol": "enqueue"}
PARSE = {"file": "app/worker.py", "start_line": 9, "end_line": 12, "symbol": "parse_document"}
HANDLERS = {"file": "app/queue.py", "start_line": 3, "end_line": 3, "symbol": "HANDLERS"}
GHOST = {"file": "app/ghost.py", "start_line": 1, "end_line": 2, "symbol": "ghost"}
S3_PUT = {"file": "app/worker.py", "start_line": 11, "end_line": 11, "symbol": "put"}


def hop(caller: dict, callee: dict, id: str, hop_type: str = "direct", **extra: Any) -> Any:  # noqa: A002
    args = {"caller": caller, "callee": callee, "kind": "call", "hop_type": hop_type, **extra}
    return resp(tool_use("record_hop", args, id))


def submit(done: bool = True, notes: str = "") -> Any:
    return resp(tool_use("submit", {"done": done, "notes": notes}, "end"))


def verdict(**fields: Any) -> Any:
    return resp(tool_use("submit", fields, "v"))


def new_ctx(repo: Path, model: ScriptedModel) -> TraceContext:
    ctx = build_context(repo, Settings(), "t1", model=model)
    ctx.store.create_trace(
        Trace(
            id="t1", question="q", entry=ENTRY, commit_sha=None, dirty=False,
            status="running", mode="eager", created_at=datetime.now(UTC), model="m",
        )
    )  # fmt: skip
    return ctx


def make(tmp_path: Path, responses: list[Any]) -> tuple[TraceContext, ScriptedModel, list[Event]]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    model = ScriptedModel(responses)
    ctx = new_ctx(repo, model)
    events: list[Event] = []
    inner = ctx.emit

    def emit(event: Event) -> object:
        events.append(event)
        return inner(event)

    ctx.emit = emit
    return ctx, model, events


ENTRY = Anchor(**UPLOAD)


def test_walk_direct_hop_code_checked(tmp_path: Path) -> None:
    ctx, model, events = make(tmp_path, [hop(UPLOAD, ACCEPT, "a"), submit()])
    result = walk_path(ctx, ENTRY, "how does upload work?")
    assert [h.verdict for h in result.hops] == ["code_checked"]
    assert len(model.requests) == 2
    h = result.hops[0]
    assert h.caller.content_hash and h.callee.content_hash and len(h.id) == 32
    assert [e.kind for e in events] == ["hop_found"]
    first = model.requests[0]["messages"][0]["content"]
    assert "how does upload work?" in first and "app/api.py:5-8 upload" in first
    assert "200" in first
    assert model.requests[0]["max_tokens"] == 4096


def test_walk_indirect_hop_goes_to_verifier(tmp_path: Path) -> None:
    script = [
        hop(ENQUEUE, PARSE, "a"),
        verdict(verdict="confirmed", evidence="HANDLERS maps it"),
        submit(),
    ]
    ctx, _, events = make(tmp_path, script)
    result = walk_path(ctx, ENTRY, "q")
    h = result.hops[0]
    assert (h.hop_type, h.verdict, h.evidence) == ("indirect", "confirmed", "HANDLERS maps it")
    assert [e.kind for e in events] == ["hop_found", "hop_verified"]
    assert events[1].data["verdict"] == "confirmed"


def test_walk_rejected_hop_returns_suggestion(tmp_path: Path) -> None:
    good = {"file": "app/queue.py", "start_line": 1, "end_line": 1, "symbol": "parse_document"}
    script = [
        hop(ENQUEUE, PARSE, "a", hop_type="indirect", wiring=HANDLERS),
        verdict(
            verdict="rejected",
            evidence="registered elsewhere",
            evidence_anchors=[good],
            suggested_callee=ACCEPT,
        ),
        submit(),
    ]
    ctx, model, _ = make(tmp_path, script)
    result = walk_path(ctx, ENTRY, "q")
    assert result.hops[0].verdict == "rejected"
    reply = model.requests[2]["messages"][-1]["content"][0]["content"]
    assert reply.startswith("rejected: registered elsewhere; suggested callee: app/documents.py")


def test_walk_bad_anchor_not_recorded(tmp_path: Path) -> None:
    ctx, model, events = make(tmp_path, [hop(UPLOAD, GHOST, "a"), submit()])
    result = walk_path(ctx, ENTRY, "q")
    assert result.hops == [] and events == []
    reply = model.requests[1]["messages"][-1]["content"][0]["content"]
    assert reply.startswith("error:") and "ghost" in reply


def test_walk_model_error_partial(tmp_path: Path) -> None:
    class Boom(ScriptedModel):
        def respond(self, **kw: Any) -> Any:
            if len(self.requests) == 2:
                raise ModelError("429")
            return super().respond(**kw)

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    script = [hop(UPLOAD, ACCEPT, "a"), hop(ACCEPT, UPLOAD, "b")]
    ctx = new_ctx(repo, Boom(script))
    result = walk_path(ctx, ENTRY, "q")
    assert result.partial_reason and "429" in result.partial_reason
    assert len(result.hops) == 2


def test_walk_hop_limit_and_effects(tmp_path: Path) -> None:
    effect = {
        "category": "object_store",
        "target": "normalized/{doc_id}",
        "op": "write",
        "anchor": S3_PUT,
    }
    script = [
        resp(tool_use("record_effect", effect, "e")),
        hop(UPLOAD, ACCEPT, "a"),
        hop(UPLOAD, ACCEPT, "b"),
        submit(done=False, notes="limit"),
    ]
    ctx, model, _ = make(tmp_path, script)
    ctx.settings = ctx.settings.model_copy(update={"max_hops": 1})
    result = walk_path(ctx, ENTRY, "q")
    assert result.effects[0].anchor.content_hash
    assert len(result.hops) == 1
    assert len(ctx.store.get_walk_effects("t1")) == 1
    reply = model.requests[3]["messages"][-1]["content"][0]["content"]
    assert reply == "hop limit reached; call submit"
    assert result.partial_reason and "limit" in result.partial_reason


def test_walk_persists_hops_as_recorded(tmp_path: Path) -> None:
    class Crash(ScriptedModel):
        def respond(self, **kw: Any) -> Any:
            if len(self.requests) == 2:
                raise RuntimeError("boom")  # not a ModelError, so walk_path does not catch it
            return super().respond(**kw)

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    script = [hop(UPLOAD, ACCEPT, "a"), hop(UPLOAD, ACCEPT, "b")]  # both direct: no verifier call
    ctx = new_ctx(repo, Crash(script))
    with pytest.raises(RuntimeError):
        walk_path(ctx, ENTRY, "q")
    assert len(ctx.store.get_hops("t1")) == 2


def test_walk_bad_wiring_anchor_keeps_hop_and_verifies(tmp_path: Path) -> None:
    script = [
        hop(UPLOAD, ACCEPT, "a", wiring=GHOST),
        verdict(verdict="unsure", evidence="cannot tell"),
        submit(),
    ]
    ctx, _, _ = make(tmp_path, script)
    result = walk_path(ctx, ENTRY, "q")
    (h,) = result.hops
    assert h.wiring is None and h.hop_type == "indirect" and h.verdict == "unsure"


def test_walk_hop_limit_marks_partial(tmp_path: Path) -> None:
    script = [hop(UPLOAD, ACCEPT, "a"), hop(ACCEPT, ENQUEUE, "b"), submit()]
    ctx, _, _ = make(tmp_path, script)
    ctx.settings = ctx.settings.model_copy(update={"max_hops": 1})
    result = walk_path(ctx, ENTRY, "q")
    assert len(result.hops) == 1
    assert result.partial_reason == "hop limit reached"


def test_record_effect_maps_old_op_and_cleans_target(tmp_path: Path) -> None:
    effect = {
        "category": "object_store",
        "target": "S3 via DocumentStorage.put",
        "op": "publish",
        "anchor": S3_PUT,
    }
    script = [resp(tool_use("record_effect", effect, "e")), submit(done=True)]
    ctx, _, _ = make(tmp_path, script)
    result = walk_path(ctx, ENTRY, "q")
    assert (result.effects[0].op, result.effects[0].target) == ("write", "DocumentStorage")


def phase_node(id: str, *anchors: dict) -> Node:  # noqa: A002
    return Node(
        id=id, level=0, parent_id=None, order=0, title="Intake", does="", input="", output="",
        boundary_reason="", anchors=tuple(Anchor(**a) for a in anchors),
    )  # fmt: skip


def test_skeleton_uses_skeleton_budget_and_prompt(tmp_path: Path) -> None:
    script = [hop(UPLOAD, ACCEPT, "a"), hop(ACCEPT, ENQUEUE, "b"), submit()]
    ctx, model, _ = make(tmp_path, script)
    ctx.settings = ctx.settings.model_copy(update={"skeleton_hops": 1})
    result = walk_skeleton(ctx, ENTRY, "q")
    assert len(result.hops) == 1 and result.partial_reason == "hop limit reached"
    assert "Hop limit: 1" in model.requests[0]["messages"][0]["content"]
    assert "stage" in model.requests[0]["system"]


def test_deepen_rejects_hops_outside_phase(tmp_path: Path) -> None:
    script = [hop(ENQUEUE, PARSE, "a"), submit()]
    ctx, model, _ = make(tmp_path, script)
    phase = phase_node("p1", UPLOAD)
    result = walk_deepen(ctx, phase, "q", 5, [])
    assert result.hops == []
    reply = model.requests[1]["messages"][-1]["content"][0]["content"]
    assert reply == "error: outside this phase; record only calls inside Intake"
    first = model.requests[0]["messages"][0]["content"]
    assert "Intake" in first and "app/api.py:5-8 upload" in first
    assert "Go into the functions that do the real work of this stage." in first


def test_deepen_goes_multiple_levels_down(tmp_path: Path) -> None:
    script = [
        hop(UPLOAD, ACCEPT, "a"),
        hop(ACCEPT, ENQUEUE, "b"),
        verdict(verdict="confirmed", evidence="accept calls enqueue"),
        submit(),
    ]
    ctx, _, _ = make(tmp_path, script)
    result = walk_deepen(ctx, phase_node("p1", UPLOAD), "q", 5, [])
    assert [h.callee.symbol for h in result.hops] == ["accept_document", "enqueue"]


def test_deepen_budget_is_its_own(tmp_path: Path) -> None:
    script = [hop(UPLOAD, ACCEPT, "a"), hop(UPLOAD, ENQUEUE, "b"), submit()]
    ctx, _, _ = make(tmp_path, script)
    result = walk_deepen(ctx, phase_node("p1", UPLOAD), "q", 1, [])
    assert len(result.hops) == 1 and result.partial_reason == "hop limit reached"


def test_deepen_budgets_weighted_and_floored(tmp_path: Path) -> None:
    ctx, _, _ = make(tmp_path, [])
    big = {"file": "app/big.py", "start_line": 1, "end_line": 90, "symbol": "big"}
    small = {"file": "app/small.py", "start_line": 1, "end_line": 10, "symbol": "small"}
    tiny = {"file": "app/tiny.py", "start_line": 1, "end_line": 1, "symbol": "tiny"}
    phases = [phase_node("a", big), phase_node("b", small), phase_node("c", tiny)]
    budgets = deepen_budgets(phases, ctx.tools, 100)
    assert budgets["a"] > budgets["b"] > budgets["c"] == 5
    assert budgets["a"] >= 80
