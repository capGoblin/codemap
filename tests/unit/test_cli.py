import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from test_service import FIXTURE, BrokenModel, RoutedModel
from typer.testing import CliRunner

from codemap import __version__
from codemap.agents.model import ModelError
from codemap.cli import main as cli_main
from codemap.cli import open as open_cmd
from codemap.service import Service
from codemap.settings import Settings
from fakes import resp, text

runner = CliRunner()
TOKEN = "sk-secret-token"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "repo"
    shutil.copytree(FIXTURE, path)
    monkeypatch.setenv("CODEMAP_CONFIG_FILE", str(tmp_path / "none.toml"))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", TOKEN)
    return path


def use_model(monkeypatch: pytest.MonkeyPatch, model: Any) -> None:
    def make(root: Path, settings: Settings) -> Service:
        return Service(root, settings, model)

    monkeypatch.setattr(cli_main, "make_service", make)


def run(repo: Path, *args: str, input: str | None = None) -> Any:
    return runner.invoke(cli_main.app, ["--repo", str(repo), *args], input=input)


def fake_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the server, the browser and the blocking wait. Return the opened URLs."""
    opened: list[str] = []
    monkeypatch.setattr(open_cmd, "serve_in_background", lambda service: "http://127.0.0.1:1")
    monkeypatch.setattr(open_cmd.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(open_cmd, "block_until_interrupt", lambda: None)
    return opened


def test_version_flag() -> None:
    result = runner.invoke(cli_main.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_trace_no_candidates_exit_1(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    result = run(repo, "trace", "nonexistent/thing.py:nothing")
    assert result.exit_code == 1
    assert 'no entry point found for "nonexistent/thing.py:nothing"' in result.output
    assert Service(repo, Settings(), None).list_traces() == []


def test_trace_pick_json(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    result = run(repo, "trace", "app/api.py:upload", "--pick", "1", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [n["title"] for n in data["nodes"] if n["level"] == 0] == ["intake", "worker"]
    assert data["trace"]["id"] in result.stderr


def test_trace_prompts_and_prints_summary(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    result = run(repo, "trace", "app/api.py:upload", "--no-open", input="\n")
    assert result.exit_code == 0, result.output
    assert "Pick entry point" in result.output
    assert "upload" in result.output
    assert "complete" in result.output
    assert "phases 2" in result.output and "steps 4" in result.output
    assert "$0.000" in result.output


def test_trace_pick_out_of_range(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    result = run(repo, "trace", "app/api.py:upload", "--pick", "5")
    assert result.exit_code == 2
    assert Service(repo, Settings(), None).list_traces() == []


def test_trace_model_error_exit_2(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, BrokenModel(ModelError("down")))
    result = run(repo, "trace", "how does upload work")
    assert result.exit_code == 2
    assert "model call failed: down" in result.output
    assert "codemap doctor" in result.output


def test_trace_ctrl_c_marks_partial(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())

    def interrupt(self: Service, trace_id: str, timeout: float | None = None) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(Service, "wait", interrupt)
    result = run(repo, "trace", "app/api.py:upload", "--pick", "1")
    assert result.exit_code == 130
    monkeypatch.undo()
    assert [t.status for t in Service(repo, Settings(), None).list_traces()] == ["partial"]


def test_open_lists_traces(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    run(repo, "trace", "app/api.py:upload", "--pick", "1", "--no-open")
    trace_id = Service(repo, Settings(), None).list_traces()[0].id
    opened = fake_browser(monkeypatch)
    result = run(repo, "open", input="\n")
    assert result.exit_code == 0
    assert opened == [f"http://127.0.0.1:1/traces/{trace_id}"]
    assert trace_id in result.output
    assert "complete" in result.output


def test_open_empty(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    result = run(repo, "open")
    assert result.exit_code == 0
    assert "no traces" in result.output


def test_doctor_missing_env_fails(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN")
    use_model(monkeypatch, BrokenModel(RuntimeError("must not be called")))
    result = run(repo, "doctor")
    assert result.exit_code == 1
    assert "ANTHROPIC_AUTH_TOKEN" in result.output
    assert "sk-" not in result.output


def test_doctor_all_pass_hides_token(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = RoutedModel()
    model.walk = [resp(text("ok"), stop="end_turn")]
    use_model(monkeypatch, model)
    result = run(repo, "doctor")
    assert TOKEN not in result.output
    assert "model" in result.output
    assert result.exit_code == 0, result.output


def test_doctor_model_failure_exit_1(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, BrokenModel(ModelError("401 bad key")))
    result = run(repo, "doctor")
    assert result.exit_code == 1
    assert "401 bad key" in result.output


def test_check_model_sends_one_tiny_request(repo: Path) -> None:
    model = RoutedModel()
    model.walk = [resp(text("ok"), stop="end_turn")]
    seen: list[dict[str, Any]] = []
    original = model.respond

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return original(**kwargs)

    model.respond = spy  # type: ignore[method-assign]
    assert Service(repo, Settings(), model).check_model() is None
    assert [(r["max_tokens"], r["tools"]) for r in seen] == [(16, [])]


def test_trace_opens_browser(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    opened = fake_browser(monkeypatch)
    result = run(repo, "trace", "app/api.py:upload", "--pick", "1")
    assert result.exit_code == 0, result.output
    trace_id = Service(repo, Settings(), None).list_traces()[0].id
    assert opened == [f"http://127.0.0.1:1/traces/{trace_id}"]


@pytest.mark.parametrize("flag", ["--no-open", "--json"])
def test_trace_without_browser(repo: Path, monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    use_model(monkeypatch, RoutedModel())
    opened = fake_browser(monkeypatch)
    monkeypatch.setattr(
        open_cmd, "serve_in_background", lambda service: pytest.fail("server started")
    )
    result = run(repo, "trace", "app/api.py:upload", "--pick", "1", flag)
    assert result.exit_code == 0, result.output
    assert opened == []


def test_open_with_id(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    run(repo, "trace", "app/api.py:upload", "--pick", "1", "--no-open")
    trace_id = Service(repo, Settings(), None).list_traces()[0].id
    opened = fake_browser(monkeypatch)
    assert run(repo, "open", trace_id).exit_code == 0
    assert opened == [f"http://127.0.0.1:1/traces/{trace_id}"]
    assert run(repo, "open", "nope").exit_code == 1
    assert len(opened) == 1


def test_serve_dev_uses_fixed_port(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_model(monkeypatch, RoutedModel())
    calls: list[int] = []
    monkeypatch.setattr(cli_main, "serve_dev", lambda service, port: calls.append(port))
    assert run(repo, "serve-dev").exit_code == 0
    assert calls == [8765]
    assert "serve-dev" not in run(repo, "--help").output
