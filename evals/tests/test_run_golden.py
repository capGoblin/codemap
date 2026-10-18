import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from codemap.agents.model import ModelResponse
from codemap.pipeline.context import prompt
from evals.run_golden import run_golden

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/sample_repo"


def a(file: str, start: int, end: int, symbol: str) -> dict[str, Any]:
    return {"file": file, "start_line": start, "end_line": end, "symbol": symbol}


UPLOAD = a("app/api.py", 5, 8, "upload")
ACCEPT = a("app/documents.py", 12, 14, "accept_document")
ENQUEUE = a("app/queue.py", 6, 7, "enqueue")
PARSE = a("app/worker.py", 9, 12, "parse_document")
STORE = a("app/storage.py", 4, 5, "store_pages")


def reply(name: str, args: dict[str, Any], id: str) -> ModelResponse:  # noqa: A002
    block = {"type": "tool_use", "id": id, "name": name, "input": args}
    return ModelResponse(content=[block], stop_reason="tool_use", input_tokens=10, output_tokens=5)


def hop(caller: dict, callee: dict, id: str, **extra: Any) -> ModelResponse:  # noqa: A002
    args = {"caller": caller, "callee": callee, "kind": "call", "hop_type": "direct", **extra}
    return reply("record_hop", args, id)


def phase(start: int, end: int, title: str) -> dict[str, Any]:
    return {
        "title": title, "does": "d", "input": "i", "output": "o",
        "boundary_reason": "b", "start": start, "end": end,
    }  # fmt: skip


def step(title: str, anchor: dict) -> dict[str, Any]:
    return {
        "title": title, "does": "d", "input": "i", "output": "o",
        "boundary_reason": "b", "anchors": [anchor], "parallel_group": None,
    }  # fmt: skip


class ScriptedModel:
    def __init__(self) -> None:
        self.walk = [
            hop(UPLOAD, ACCEPT, "h1"),
            hop(UPLOAD, ENQUEUE, "h2"),
            hop(ENQUEUE, PARSE, "h3", kind="async", hop_type="indirect"),
            reply("submit", {"verdict": "confirmed", "evidence": "HANDLERS"}, "v"),
            hop(PARSE, STORE, "h4"),
            reply("submit", {"done": True}, "s"),
        ]
        self.steps = {
            "intake": [step("accept", ACCEPT), step("queue", ENQUEUE)],
            "worker": [step("parse", PARSE), step("store", STORE)],
        }

    def respond(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Any:
        if system == prompt("walk_deepen"):
            return reply("submit", {"done": True}, "d")
        if system == prompt("split_phases"):
            return reply("submit", {"phases": [phase(0, 2, "intake"), phase(3, 4, "worker")]}, "p")
        if system == prompt("phase_effects"):
            return reply("submit", {"effects": []}, "e")
        if system == prompt("split_steps"):
            first = messages[0]["content"]
            steps = next((v for k, v in self.steps.items() if f"Phase: {k}\n" in first), [])
            return reply("submit", {"steps": steps}, "t")
        return self.walk.pop(0)


def expected_json(repo: Path, commit: str) -> str:
    def node(title: str, spans: list[dict], steps: list[dict]) -> dict[str, Any]:
        return {"title": title, "spans": spans, "steps": steps}

    intake = node("intake", [ACCEPT, ENQUEUE], [node("accept", [ACCEPT], [])])
    worker = node("worker", [PARSE, STORE], [node("parse", [PARSE], [])])
    return json.dumps(
        {
            "repo": str(repo),
            "commit": commit,
            "question": "q",
            "entry": UPLOAD,
            "phases": [intake, worker],
            "effects": [],
        }
    )


def committed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    env = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", *env, "commit", "-qm", "x"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    )
    return repo, head.stdout.strip()


def test_golden_flow_scores_a_scripted_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, head = committed_repo(tmp_path)
    path = tmp_path / "t.expected.json"
    path.write_text(expected_json(repo, head))
    result = run_golden(path, record=False, model=ScriptedModel())
    assert result.status == "complete"
    assert result.phase_agreement > 0.5
    assert result.off_path_nodes == 0
    assert "complete" in capsys.readouterr().out


def test_head_mismatch_refuses_to_run(tmp_path: Path) -> None:
    repo, head = committed_repo(tmp_path)
    path = tmp_path / "t.expected.json"
    path.write_text(expected_json(repo, "0" * 40))
    with pytest.raises(RuntimeError, match=head):
        run_golden(path, record=False, model=ScriptedModel())


def test_dirty_tree_prints_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, head = committed_repo(tmp_path)
    (repo / "new.txt").write_text("x")
    path = tmp_path / "t.expected.json"
    path.write_text(expected_json(repo, head))
    run_golden(path, record=False, model=ScriptedModel())
    assert "uncommitted changes" in capsys.readouterr().out
