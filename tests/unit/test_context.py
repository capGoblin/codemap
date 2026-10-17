import shutil
from pathlib import Path

import pytest

from codemap.pipeline.context import build_context, prompt, read_tools
from codemap.repo.ignore import RepoIgnore
from codemap.repo.tools import RepoTools
from codemap.settings import Settings
from fakes import ScriptedModel

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"
PROMPTS = ["resolve", "walk", "verify", "split_phases", "split_steps"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_read_tools_names(repo: Path) -> None:
    tools = read_tools(RepoTools(repo, RepoIgnore(repo)))
    assert {t.name for t in tools} == {
        "list_dir",
        "read_file",
        "search",
        "find_definition",
        "outline",
    }
    assert all(t.input_schema["type"] == "object" for t in tools)


def test_read_tool_handler_calls_tools(repo: Path) -> None:
    tools = {t.name: t for t in read_tools(RepoTools(repo, RepoIgnore(repo)))}
    out = tools["read_file"].handler({"path": "app/api.py", "start": 1, "end": 2})
    assert out.startswith("1: ")
    assert "\n2: " in out


@pytest.mark.parametrize("name", PROMPTS)
def test_prompt_loads(name: str) -> None:
    text = prompt(name)
    assert text.strip()
    assert len(text.splitlines()) < 60


def test_build_context(repo: Path) -> None:
    model = ScriptedModel([])
    ctx = build_context(repo, Settings(), "t1", model=model)
    assert (repo / ".codemap" / "codemap.db").is_file()
    assert ctx.trace_id == "t1"
    assert ctx.tools.index is not None
    assert ctx.model is not model
    assert ctx.budget.cost_usd == 0
