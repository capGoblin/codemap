import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codemap.domain.models import Anchor, Hop, Node, Trace
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.explain import ExplainError, call_links, explain_node
from codemap.settings import Settings
from fakes import ScriptedModel, resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


def a(file: str, start: int, end: int, symbol: str) -> Anchor:
    return Anchor(file=file, start_line=start, end_line=end, symbol=symbol)


UPLOAD = a("app/api.py", 5, 8, "upload")
ACCEPT = a("app/documents.py", 12, 14, "accept_document")


def node(id: str, level: int, anchors: tuple[Anchor, ...], parent: str | None = None) -> Node:
    return Node(
        id=id, level=level, parent_id=parent, order=0, title=id, does="", input="", output="",
        boundary_reason="", anchors=anchors,
    )  # fmt: skip


PHASE = node("phase", 0, (UPLOAD,))
HOP = Hop(id="h1", caller=UPLOAD, callee=ACCEPT, kind="call", hop_type="direct")


def make_ctx(tmp_path: Path, model: Any) -> TraceContext:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    ctx = build_context(repo, Settings(), "t1", model=model)
    ctx.store.create_trace(
        Trace(
            id="t1",
            question="q",
            entry=UPLOAD,
            commit_sha=None,
            dirty=False,
            status="complete",
            mode="eager",
            created_at=datetime.now(UTC),
            model="m",
        )  # fmt: skip
    )
    return ctx


def step(text: str, file: str, first: int, last: int) -> dict[str, Any]:
    return {"text": text, "file": file, "lines": [first, last]}


def answer(*steps: dict[str, Any], **io: Any) -> Any:
    return resp(tool_use("submit", {"steps": list(steps), **io}, "s1"))


def test_grounding_drops_bad_cites(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            answer(
                step("ok", "app/api.py", 5, 6),
                step("wrong file", "app/other.py", 5, 6),
                step("past the anchor", "app/api.py", 7, 20),
                step("backwards", "app/api.py", 6, 5),
                step("hop caller range", "app/api.py", 5, 8),
            )
        ]
    )
    ctx = make_ctx(tmp_path, model)
    ctx.store.save_nodes("t1", [PHASE], [])
    explain = explain_node(ctx, PHASE, [HOP], [])
    assert [s.text for s in explain.steps] == ["ok", "hop caller range"]


def test_cite_in_hop_caller_range_under_node(tmp_path: Path) -> None:
    child = node("child", 1, (a("app/api.py", 5, 6, "upload"),), parent="phase")
    hop = Hop(id="h", caller=UPLOAD, callee=ACCEPT, kind="call", hop_type="direct")
    ctx = make_ctx(tmp_path, ScriptedModel([answer(step("wider", "app/api.py", 5, 8))]))
    ctx.store.save_nodes("t1", [PHASE, child], [])
    assert len(explain_node(ctx, child, [hop], []).steps) == 1


def test_no_grounded_step_raises(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ScriptedModel([answer(step("x", "app/nope.py", 1, 2))]))
    ctx.store.save_nodes("t1", [PHASE], [])
    with pytest.raises(ExplainError):
        explain_node(ctx, PHASE, [], [])


def test_unknown_io_node_id_cleared(tmp_path: Path) -> None:
    other = node("other", 0, (ACCEPT,))
    model = ScriptedModel(
        [
            answer(
                step("ok", "app/api.py", 5, 6),
                input={"type": "Request", "fields": ["file"], "node_id": "ghost"},
                output={"type": "Doc", "node_id": "other"},
            )
        ]
    )
    ctx = make_ctx(tmp_path, model)
    ctx.store.save_nodes("t1", [PHASE, other], [])
    explain = explain_node(ctx, PHASE, [], [])
    assert explain.input.node_id is None
    assert explain.input.type == "Request"
    assert explain.output.node_id == "other"
    assert "other: other" in model.requests[0]["messages"][0]["content"]


def test_call_links_point_to_deepest_other_node() -> None:
    step_node = node("step", 1, (ACCEPT,), parent="target")
    target = node("target", 0, (ACCEPT,))
    links = call_links(PHASE, [PHASE, target, step_node], [HOP])
    assert [(c.symbol, c.node_id) for c in links] == [("accept_document", "step")]
    assert call_links(PHASE, [PHASE], [HOP])[0].node_id is None
