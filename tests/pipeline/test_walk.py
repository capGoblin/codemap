import shutil
from pathlib import Path
from typing import Any

from codemap.agents.model import ModelError
from codemap.domain.events import Event
from codemap.domain.models import Anchor
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.walk import walk_path
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


def make(tmp_path: Path, responses: list[Any]) -> tuple[TraceContext, ScriptedModel, list[Event]]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    model = ScriptedModel(responses)
    ctx = build_context(repo, Settings(), "t1", model=model)
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
    ctx = build_context(repo, Settings(), "t1", model=Boom(script))
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
    reply = model.requests[3]["messages"][-1]["content"][0]["content"]
    assert reply == "hop limit reached; call submit"
    assert result.partial_reason and "limit" in result.partial_reason
