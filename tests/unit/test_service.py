import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from codemap.agents.model import ModelError
from codemap.domain.models import Anchor, EntryCandidate, TraceMode
from codemap.logs import setup_logging
from codemap.pipeline.context import prompt
from codemap.service import Service
from codemap.settings import Settings
from fakes import resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


def a(file: str, start: int, end: int, symbol: str) -> dict[str, Any]:
    return {"file": file, "start_line": start, "end_line": end, "symbol": symbol}


UPLOAD = a("app/api.py", 5, 8, "upload")
ACCEPT = a("app/documents.py", 12, 14, "accept_document")
ENQUEUE = a("app/queue.py", 6, 7, "enqueue")
PARSE = a("app/worker.py", 9, 12, "parse_document")
STORE = a("app/storage.py", 4, 5, "store_pages")
ENTRY = EntryCandidate(anchor=Anchor(**UPLOAD), label="upload", reason="r")


def hop(caller: dict, callee: dict, id: str, kind: str = "call", **extra: Any) -> Any:  # noqa: A002
    args = {"caller": caller, "callee": callee, "kind": kind, "hop_type": "direct", **extra}
    return resp(tool_use("record_hop", args, id))


def submit(**fields: Any) -> Any:
    return resp(tool_use("submit", fields, "s"))


def phase_draft(start: int, end: int, title: str) -> dict[str, Any]:
    return {
        "title": title, "does": "does", "input": "in", "output": "out",
        "boundary_reason": "why", "start": start, "end": end,
    }  # fmt: skip


def step_draft(title: str, anchors: list[dict]) -> dict[str, Any]:
    return {
        "title": title, "does": "does", "input": "in", "output": "out",
        "boundary_reason": "why", "anchors": anchors, "parallel_group": None,
    }  # fmt: skip


class RoutedModel:
    def __init__(self) -> None:
        self.walk = [
            hop(UPLOAD, ACCEPT, "h1"),
            hop(UPLOAD, ENQUEUE, "h2"),
            hop(ENQUEUE, PARSE, "h3", kind="async", hop_type="indirect"),
            resp(tool_use("submit", {"verdict": "confirmed", "evidence": "HANDLERS"}, "v")),
            hop(PARSE, STORE, "h4"),
            submit(done=True),
        ]
        self.phases = submit(phases=[phase_draft(0, 2, "intake"), phase_draft(3, 4, "worker")])
        self.explain = submit(
            steps=[
                {"text": "Inserts the document row.", "file": "app/documents.py", "lines": [12, 14]}
            ],
            input={"type": "File", "fields": ["name"]},
            output={"type": "Doc", "fields": ["id", "status"]},
        )
        self.steps = {
            "intake": submit(
                steps=[step_draft("accept", [ACCEPT]), step_draft("queue", [ENQUEUE])]
            ),
            "worker": submit(steps=[step_draft("parse", [PARSE]), step_draft("store", [STORE])]),
        }

    def respond(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Any:
        if system == prompt("split_phases"):
            return self.phases
        if system == prompt("split_steps"):
            first = messages[0]["content"]
            return next(r for title, r in self.steps.items() if f"Phase: {title}\n" in first)
        if system == prompt("explain"):
            return self.explain
        return self.walk.pop(0)


class BrokenModel:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def respond(self, **_: Any) -> Any:
        raise self.error


def make(tmp_path: Path, model: Any, git: bool = False) -> tuple[Service, Path]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    if git:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return Service(repo, Settings(), model), repo


def trace(svc: Service, mode: TraceMode = "eager") -> str:
    entry = svc.resolve("app/api.py:upload")[0]  # direct entry: hashed, no model call
    trace_id = svc.start_trace("q", entry, mode)
    assert svc.wait(trace_id, 30) == "complete"
    return trace_id


def test_git_exclude_added_once(tmp_path: Path) -> None:
    _, repo = make(tmp_path, RoutedModel(), git=True)
    Service(repo, Settings(), RoutedModel())
    lines = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert lines.count(".codemap/") == 1


def test_non_git_repo_commit_none(tmp_path: Path) -> None:
    svc, repo = make(tmp_path, RoutedModel())
    assert not (repo / ".git").exists()
    trace_id = trace(svc)
    got = svc.list_traces()[0]
    assert (got.id, got.commit_sha, got.dirty) == (trace_id, None, False)


def test_git_trace_records_commit_and_dirty(tmp_path: Path) -> None:
    svc, repo = make(tmp_path, RoutedModel(), git=True)
    env = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", *env, "commit", "-qm", "x"], cwd=repo, check=True)
    (repo / "new.txt").write_text("x")
    trace(svc)
    got = svc.list_traces()[0]
    assert got.commit_sha and len(got.commit_sha) == 40
    assert got.dirty is True


def test_start_and_wait_complete(tmp_path: Path) -> None:
    svc, _ = make(tmp_path, RoutedModel())
    trace_id = trace(svc)
    graph = svc.get_graph(trace_id, depth=1)
    assert graph.trace.status == "complete"
    assert [n.title for n in graph.nodes if n.level == 0] == ["intake", "worker"]
    assert svc.events(trace_id)[-1][1].kind == "finished"


def test_thread_exception_marks_failed(tmp_path: Path) -> None:
    svc, _ = make(tmp_path, BrokenModel(RuntimeError("boom")))
    trace_id = svc.start_trace("q", ENTRY, "eager")
    assert svc.wait(trace_id, 30) == "failed"
    kind, message = [(e.kind, e.message) for _, e in svc.events(trace_id)][-1]
    assert (kind, message) == ("finished", "boom")


def test_construction_marks_running_partial(tmp_path: Path) -> None:
    svc, repo = make(tmp_path, RoutedModel())
    trace_id = trace(svc)
    svc._store.set_status(trace_id, "running")
    assert Service(repo, Settings(), None).list_traces()[0].status == "partial"


def test_get_graph_marks_stale(tmp_path: Path) -> None:
    svc, repo = make(tmp_path, RoutedModel())
    trace_id = trace(svc)
    assert not any(n.stale for n in svc.get_graph(trace_id).nodes)
    path = repo / "app" / "documents.py"
    lines = path.read_text().splitlines()
    lines[12] += "  # edited"
    path.write_text("\n".join(lines) + "\n")
    nodes = svc.get_graph(trace_id).nodes
    assert sorted(n.title for n in nodes if n.stale) == ["accept", "intake"]


def test_expand_node_and_detail(tmp_path: Path) -> None:
    svc, _ = make(tmp_path, RoutedModel())
    trace_id = trace(svc, "lazy")
    phase = next(n for n in svc.get_graph(trace_id).nodes if n.title == "intake")
    graph = svc.expand_node(trace_id, phase.id)
    assert sorted(n.title for n in graph.nodes if n.level == 1) == ["accept", "queue"]
    details = svc.get_detail(trace_id, phase.id).functions
    accept = next(d for d in details if d.anchor.symbol == "accept_document")
    assert "def accept_document" in accept.code


def test_get_detail_unknown_node(tmp_path: Path) -> None:
    svc, _ = make(tmp_path, RoutedModel())
    with pytest.raises(KeyError):
        svc.get_detail(trace(svc), "nope")


def test_resolve_direct_entry(tmp_path: Path) -> None:
    svc, _ = make(tmp_path, BrokenModel(RuntimeError("unused")))
    found = svc.resolve("app/api.py:upload")
    assert [c.anchor.symbol for c in found] == ["upload"]


def test_resolve_propagates_model_error(tmp_path: Path) -> None:
    svc, _ = make(tmp_path, BrokenModel(ModelError("down")))
    with pytest.raises(ModelError):
        svc.resolve("how does upload work")


def test_log_redacts_token(tmp_path: Path) -> None:
    setup_logging(tmp_path, verbose=False, token="sk-secret")
    log = logging.getLogger("codemap.test")
    log.info("token sk-secret in message")
    log.info("token %s in args", "sk-secret")
    try:
        raise RuntimeError("bad sk-secret")
    except RuntimeError:
        log.exception("failed")
    for h in logging.getLogger("codemap").handlers:
        h.flush()
    text = (tmp_path / ".codemap" / "logs" / "codemap.log").read_text()
    assert "sk-secret" not in text
    assert text.count("***") >= 3


def test_cancel_stops_a_running_trace_as_partial(tmp_path: Path) -> None:
    import threading

    started, release = threading.Event(), threading.Event()

    class Blocking:
        def respond(self, **_: Any) -> Any:
            started.set()
            release.wait(30)
            raise ModelError("unblocked")

    svc, _ = make(tmp_path, Blocking())
    entry = svc.resolve("app/api.py:upload")[0]
    trace_id = svc.start_trace("q", entry, "eager")
    assert started.wait(10)
    svc.cancel(trace_id)
    release.set()
    assert svc.wait(trace_id, 5) == "partial"
    last = svc.events(trace_id)[-1][1]
    assert last.kind == "finished" and last.data == {"status": "partial"}


class CountingModel(RoutedModel):
    def __init__(self) -> None:
        super().__init__()
        self.explain_calls = 0

    def respond(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Any:
        if system == prompt("explain"):
            self.explain_calls += 1
        return super().respond(system=system, messages=messages, tools=tools, max_tokens=max_tokens)


def test_detail_explains_once_then_reads_store(tmp_path: Path) -> None:
    model = CountingModel()
    svc, _ = make(tmp_path, model)
    trace_id = trace(svc)
    accept = next(n for n in svc.get_graph(trace_id).nodes if n.title == "accept")
    first = svc.get_detail(trace_id, accept.id)
    assert first.explain is not None and first.explain_error is None
    assert first.explain.steps[0].file == "app/documents.py"
    second = svc.get_detail(trace_id, accept.id)
    assert second.explain == first.explain
    assert model.explain_calls == 1


def test_detail_model_error_keeps_deterministic_parts(tmp_path: Path) -> None:
    model = CountingModel()
    svc, _ = make(tmp_path, model)
    trace_id = trace(svc)
    svc._model = BrokenModel(ModelError("down"))  # type: ignore[assignment]
    phase = next(n for n in svc.get_graph(trace_id).nodes if n.title == "intake")
    detail = svc.get_detail(trace_id, phase.id)
    assert detail.explain is None
    assert detail.explain_error == "down"
    assert any("def accept_document" in f.code for f in detail.functions)
    assert [c.symbol for c in detail.calls] == [
        "accept_document",
        "enqueue",
        "parse_document",
    ]
    graph = svc.get_graph(trace_id, 1)
    step_ids = {n.title: n.id for n in graph.nodes if n.level == 1}
    assert [c.node_id for c in detail.calls] == [
        step_ids["accept"],
        step_ids["queue"],
        step_ids["parse"],
    ]


def test_regenerate_detail_makes_a_new_explain(tmp_path: Path) -> None:
    model = CountingModel()
    svc, _ = make(tmp_path, model)
    trace_id = trace(svc)
    accept = next(n for n in svc.get_graph(trace_id).nodes if n.title == "accept")
    svc.get_detail(trace_id, accept.id)
    svc._model = BrokenModel(ModelError("down"))  # type: ignore[assignment]
    failed = svc.regenerate_detail(trace_id, accept.id)
    assert failed.explain_error == "down"
    assert failed.explain is not None  # the stored one stays
