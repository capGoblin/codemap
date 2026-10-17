import shutil
from pathlib import Path
from typing import Any

import pytest

from codemap.agents.model import ModelError
from codemap.domain.models import Anchor, Hop
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.verify import verify_hop
from codemap.repo.anchors import with_hash
from codemap.settings import Settings
from fakes import ScriptedModel, resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


class FailingModel:
    def respond(self, **_: Any) -> Any:
        raise ModelError("boom")


def submit(**fields: Any) -> Any:
    return resp(tool_use("submit", fields, "s1"))


def make_ctx(tmp_path: Path, model: Any) -> TraceContext:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return build_context(repo, Settings(), "t1", model=model)


def make_hop(ctx: TraceContext) -> Hop:
    caller = Anchor(file="app/queue.py", start_line=6, end_line=7, symbol="enqueue")
    callee = Anchor(file="app/worker.py", start_line=9, end_line=12, symbol="parse_document")
    return Hop(
        id="h1",
        caller=with_hash(ctx.tools, caller),
        callee=with_hash(ctx.tools, callee),
        kind="call",
        hop_type="indirect",
        wiring=Anchor(file="app/queue.py", start_line=3, end_line=3, symbol="HANDLERS"),
    )


def run(tmp_path: Path, model: Any) -> Any:
    ctx = make_ctx(tmp_path, model)
    return verify_hop(ctx, make_hop(ctx))


def test_confirmed(tmp_path: Path) -> None:
    model = ScriptedModel([submit(verdict="confirmed", evidence="HANDLERS maps it")])
    assert run(tmp_path, model).verdict == "confirmed"


def test_rejected_without_evidence_becomes_unsure(tmp_path: Path) -> None:
    model = ScriptedModel([submit(verdict="rejected", evidence="")])
    assert run(tmp_path, model).verdict == "unsure"


def test_rejected_with_bad_anchor_becomes_unsure(tmp_path: Path) -> None:
    bad = {"file": "app/nope.py", "start_line": 1, "end_line": 1, "symbol": "x"}
    model = ScriptedModel(
        [submit(verdict="rejected", evidence="it is elsewhere", evidence_anchors=[bad])]
    )
    assert run(tmp_path, model).verdict == "unsure"


def test_rejected_with_evidence_kept(tmp_path: Path) -> None:
    good = {"file": "app/queue.py", "start_line": 1, "end_line": 1, "symbol": "parse_document"}
    model = ScriptedModel(
        [submit(verdict="rejected", evidence="registered elsewhere", evidence_anchors=[good])]
    )
    assert run(tmp_path, model).verdict == "rejected"


def test_bad_suggested_callee_dropped(tmp_path: Path) -> None:
    bad = {"file": "app/nope.py", "start_line": 1, "end_line": 1, "symbol": "x"}
    model = ScriptedModel([submit(verdict="unsure", evidence="maybe", suggested_callee=bad)])
    assert run(tmp_path, model).suggested_callee is None


def test_user_message_has_only_claim(tmp_path: Path) -> None:
    model = ScriptedModel([submit(verdict="confirmed", evidence="ok")])
    run(tmp_path, model)
    messages = model.requests[0]["messages"]
    assert len(messages) == 1
    assert "app/queue.py" in messages[0]["content"]
    assert "parse_document" in messages[0]["content"]


def test_cache_hit_skips_model(tmp_path: Path) -> None:
    model = ScriptedModel([submit(verdict="confirmed", evidence="ok")])
    ctx = make_ctx(tmp_path, model)
    hop = make_hop(ctx)
    first = verify_hop(ctx, hop)
    assert verify_hop(ctx, hop) == first
    assert len(model.requests) == 1


def test_model_error_gives_unsure(tmp_path: Path) -> None:
    result = run(tmp_path, FailingModel())
    assert result.verdict == "unsure"
    assert result.evidence.startswith("verifier unavailable:")


@pytest.mark.parametrize("name", ["evidence_anchors", "suggested_callee"])
def test_prompt_names_submit_fields(name: str) -> None:
    from codemap.pipeline.context import prompt

    assert name in prompt("verify")
