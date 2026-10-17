import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codemap.domain.models import TraceMode
from codemap.pipeline.context import prompt
from codemap.server.app import create_app
from codemap.service import Service
from codemap.settings import Settings
from fakes import resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


def _a(file: str, start: int, end: int, symbol: str) -> dict[str, Any]:
    return {"file": file, "start_line": start, "end_line": end, "symbol": symbol}


UPLOAD = _a("app/api.py", 5, 8, "upload")
ACCEPT = _a("app/documents.py", 12, 14, "accept_document")
ENQUEUE = _a("app/queue.py", 6, 7, "enqueue")
PARSE = _a("app/worker.py", 9, 12, "parse_document")
STORE = _a("app/storage.py", 4, 5, "store_pages")


def _hop(caller: dict, callee: dict, id: str, **extra: Any) -> Any:  # noqa: A002
    args = {"caller": caller, "callee": callee, "kind": "call", "hop_type": "direct", **extra}
    return resp(tool_use("record_hop", args, id))


def _submit(**fields: Any) -> Any:
    return resp(tool_use("submit", fields, "s"))


def _phase(start: int, end: int, title: str) -> dict[str, Any]:
    return {
        "title": title, "does": "does", "input": "in", "output": "out",
        "boundary_reason": "why", "start": start, "end": end,
    }  # fmt: skip


def _step(title: str, anchors: list[dict]) -> dict[str, Any]:
    return {
        "title": title, "does": "does", "input": "in", "output": "out",
        "boundary_reason": "why", "anchors": anchors, "parallel_group": None,
    }  # fmt: skip


class RoutedModel:
    """Scripted full run over the sample repo: phases `intake` and `worker`."""

    def __init__(self) -> None:
        self.walk = [
            _hop(UPLOAD, ACCEPT, "h1"),
            _hop(UPLOAD, ENQUEUE, "h2"),
            _hop(ENQUEUE, PARSE, "h3", kind="async", hop_type="indirect"),
            resp(tool_use("submit", {"verdict": "confirmed", "evidence": "HANDLERS"}, "v")),
            _hop(PARSE, STORE, "h4"),
            _submit(done=True),
        ]
        self.phases = _submit(phases=[_phase(0, 2, "intake"), _phase(3, 4, "worker")])
        self.explain = _submit(
            steps=[
                {"text": "Inserts the document row.", "file": "app/documents.py", "lines": [12, 14]}
            ],
            input={"type": "File", "fields": ["name"]},
            output={"type": "Doc", "fields": ["id", "status"]},
        )
        self.steps = {
            "intake": _submit(steps=[_step("accept", [ACCEPT]), _step("queue", [ENQUEUE])]),
            "worker": _submit(steps=[_step("parse", [PARSE]), _step("store", [STORE])]),
        }

    def respond(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Any:
        if system == prompt("walk_deepen"):
            return _submit(done=True)
        if system == prompt("split_phases"):
            return self.phases
        if system == prompt("split_steps"):
            first = messages[0]["content"]
            return next(r for title, r in self.steps.items() if f"Phase: {title}\n" in first)
        if system == prompt("explain"):
            return self.explain
        return self.walk.pop(0)


MakeTrace = Callable[[TraceMode], str]


@pytest.fixture
def service(tmp_path: Path) -> Service:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return Service(repo, Settings(), RoutedModel())


@pytest.fixture
def make_trace(service: Service) -> MakeTrace:
    def make(mode: TraceMode = "eager") -> str:
        entry = service.resolve("app/api.py:upload")[0]
        trace_id = service.start_trace("q", entry, mode)
        assert service.wait(trace_id, 30) == "complete"
        return trace_id

    return make


@pytest.fixture
def client(service: Service) -> TestClient:
    return TestClient(create_app(service, None))
