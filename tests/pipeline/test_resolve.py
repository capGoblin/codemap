import shutil
from pathlib import Path
from typing import Any

import pytest

from codemap.agents.limits import Budget, Limits
from codemap.agents.model import ModelError
from codemap.pipeline.context import TraceContext
from codemap.pipeline.resolve import parse_direct_entry, resolve_entry
from codemap.repo.ignore import RepoIgnore
from codemap.repo.index import MemorySymbolCache, SymbolIndex
from codemap.repo.tools import RepoTools
from fakes import ScriptedModel, resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


def make_ctx(root: Path, model: Any, limits: Limits | None = None) -> TraceContext:
    tools = RepoTools(root, RepoIgnore(root))
    tools.index = SymbolIndex(tools, MemorySymbolCache())
    budget = Budget(limits or Limits(3600, 10**9, 100.0, 1000), 0.0, 0.0)
    return TraceContext(
        root=root,
        tools=tools,
        model=model,
        budget=budget,
        store=None,  # type: ignore[arg-type]
        verdicts=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]
        emit=lambda e: None,
        trace_id="t",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


def cand(file: str, start: int, end: int, symbol: str) -> dict[str, Any]:
    return {
        "anchor": {"file": file, "start_line": start, "end_line": end, "symbol": symbol},
        "label": symbol,
        "reason": "because",
    }


def submit(*cands: dict[str, Any]) -> Any:
    return resp(tool_use("submit", {"candidates": list(cands)}, "s1"))


def test_parse_direct_entry() -> None:
    assert parse_direct_entry("app/api.py:upload") == ("app/api.py", "upload")
    assert parse_direct_entry("a/b.py:Cls.run") == ("a/b.py", "Cls.run")
    assert parse_direct_entry("file parsing system") is None
    assert parse_direct_entry("see note: this") is None


def test_direct_entry_no_model(repo: Path) -> None:
    model = ScriptedModel([])
    result = resolve_entry(make_ctx(repo, model), "app/api.py:upload")
    assert len(result) == 1
    anchor = result[0].anchor
    assert (anchor.file, anchor.start_line, anchor.end_line) == ("app/api.py", 5, 8)
    assert anchor.content_hash
    assert model.requests == []


def test_direct_entry_missing_symbol(repo: Path) -> None:
    assert resolve_entry(make_ctx(repo, ScriptedModel([])), "app/api.py:nope") == []


def test_direct_dotted_symbol_uses_class_to_disambiguate(repo: Path) -> None:
    (repo / "app" / "two.py").write_text(
        "class A:\n    def run(self):\n        pass\n\n\n"
        "class B:\n    def run(self):\n        pass\n"
    )
    result = resolve_entry(make_ctx(repo, ScriptedModel([])), "app/two.py:B.run")
    assert [(c.anchor.start_line, c.anchor.end_line) for c in result] == [(7, 8)]


def test_agent_candidates_validated(repo: Path) -> None:
    model = ScriptedModel(
        [submit(cand("app/api.py", 5, 8, "upload"), cand("app/ghost.py", 1, 3, "x"))]
    )
    result = resolve_entry(make_ctx(repo, model), "file parsing system")
    assert [c.anchor.file for c in result] == ["app/api.py"]
    assert result[0].anchor.content_hash


def test_no_candidates_returns_empty(repo: Path) -> None:
    result = resolve_entry(make_ctx(repo, ScriptedModel([submit()])), "nothing here")
    assert result == []


def test_more_than_five_candidates_rejected_then_retry(repo: Path) -> None:
    six = [cand("app/api.py", 5, 8, "upload")] * 6
    model = ScriptedModel([submit(*six), submit(cand("app/api.py", 5, 8, "upload"))])
    assert len(resolve_entry(make_ctx(repo, model), "upload")) == 1


def test_limit_reached_returns_empty(repo: Path) -> None:
    ctx = make_ctx(repo, ScriptedModel([]), Limits(3600, 10**9, 100.0, 0))
    ctx.budget.count_tool_call()
    assert resolve_entry(ctx, "anything") == []


def test_model_error_propagates(repo: Path) -> None:
    class Failing:
        def respond(self, **_: Any) -> Any:
            raise ModelError("boom")

    with pytest.raises(ModelError):
        resolve_entry(make_ctx(repo, Failing()), "anything")
