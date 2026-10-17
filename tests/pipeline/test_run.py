import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codemap.agents.model import ModelError, ModelResponse
from codemap.domain.events import Event
from codemap.domain.models import Anchor, Trace, TraceMode
from codemap.pipeline.context import TraceContext, build_context, prompt
from codemap.pipeline.run import expand_phase, run_trace
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
INSERT = a("app/documents.py", 13, 13, "insert")
PUT = a("app/worker.py", 11, 11, "put")
ERR = a("app/db.py", 1, 2, "insert")
ENTRY = Anchor(**UPLOAD)


def hop(caller: dict, callee: dict, id: str, kind: str = "call", **extra: Any) -> Any:  # noqa: A002
    args = {"caller": caller, "callee": callee, "kind": kind, "hop_type": "direct", **extra}
    return resp(tool_use("record_hop", args, id))


def effect(category: str, target: str, anchor: dict, id: str) -> Any:  # noqa: A002
    args = {"category": category, "target": target, "op": "write", "anchor": anchor}
    return resp(tool_use("record_effect", args, id))


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
    """Route by prompt so split workers on threads get stable answers.

    Walk and verifier turns pop from one ordered queue. Phase and step splits are looked up.
    """

    def __init__(self, walk: list[Any], phases: Any, steps: dict[str, Any]) -> None:
        self.walk = list(walk)
        self.phases = phases
        self.steps = steps

    def respond(self, *, system: str, messages: list, tools: list, max_tokens: int) -> Any:
        if system == prompt("split_phases"):
            return self.phases
        if system == prompt("split_steps"):
            first = messages[0]["content"]
            return next(r for title, r in self.steps.items() if f"Phase: {title}\n" in first)
        return self.walk.pop(0)


STEPS = {
    "intake": submit(steps=[step_draft("accept", [ACCEPT]), step_draft("queue", [ENQUEUE])]),
    "worker": submit(steps=[step_draft("parse", [PARSE]), step_draft("store", [STORE])]),
}
PHASES = submit(phases=[phase_draft(0, 2, "intake"), phase_draft(3, 4, "worker")])
FULL_WALK = [
    effect("db", "document", INSERT, "e1"),
    effect("object_store", "normalized/{doc_id}", PUT, "e2"),
    hop(UPLOAD, ACCEPT, "h1"),
    hop(UPLOAD, ENQUEUE, "h2"),
    hop(ENQUEUE, PARSE, "h3", kind="async", hop_type="indirect"),
    resp(tool_use("submit", {"verdict": "confirmed", "evidence": "HANDLERS"}, "v")),
    hop(PARSE, STORE, "h4"),
    submit(done=True),
]


def full_model() -> RoutedModel:
    return RoutedModel(FULL_WALK, PHASES, STEPS)


def setup(
    tmp_path: Path, model: Any, mode: TraceMode = "eager", git: bool = True
) -> tuple[TraceContext, list[Event]]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    ctx = build_context(repo, Settings(), "t1", model=model)
    ctx.store.create_trace(
        Trace(
            id="t1", question="q", entry=ENTRY, commit_sha="abc" if git else None, dirty=False,
            status="running", mode=mode, created_at=datetime.now(UTC), model="m",
        )
    )  # fmt: skip
    events: list[Event] = []
    inner = ctx.emit

    def emit(event: Event) -> object:
        events.append(event)
        return inner(event)

    ctx.emit = emit
    return ctx, events


def test_run_trace_eager_end_to_end(tmp_path: Path) -> None:
    ctx, events = setup(tmp_path, full_model())
    assert run_trace(ctx, "q", ENTRY, "eager") == "complete"
    graph = ctx.store.get_graph("t1", 1)
    assert graph.trace.status == "complete"
    phases = [n for n in graph.nodes if n.level == 0]
    steps = [n for n in graph.nodes if n.level == 1]
    assert [p.title for p in phases] == ["intake", "worker"]
    assert len(steps) == 4
    effects = {(e.category, e.target, e.op) for p in phases for e in p.effects}
    assert effects == {
        ("db", "document", "write"),
        ("object_store", "normalized/{doc_id}", "write"),
    }
    kinds = {(e.source_id, e.target_id): e.kind for e in graph.edges}
    assert kinds[(phases[0].id, phases[1].id)] == "async"
    assert all(n.anchors[0].file != "app/unused.py" for n in graph.nodes)
    assert len(ctx.store.get_hops("t1")) == 4
    assert len(ctx.store.get_walk_effects("t1")) == 2
    assert graph.trace.input_tokens > 0


def test_run_trace_events_in_order(tmp_path: Path) -> None:
    ctx, events = setup(tmp_path, full_model())
    run_trace(ctx, "q", ENTRY, "eager")
    started = [e.message for e in events if e.kind == "step_started"]
    assert len(started) == 5
    splits = [e for e in events if e.kind == "phase_split"]
    assert len(splits) == 4
    assert all("phase_id" in e.data for e in splits)
    assert [e.data.get("steps") for e in splits[2:]] == [2, 2]
    assert events[-1].kind == "finished" and events[-1].data == {"status": "complete"}
    kinds = [e.kind for e in events]
    assert kinds.index("phase_split") < kinds.index("finished")


def test_run_trace_lazy_then_expand(tmp_path: Path) -> None:
    ctx, _ = setup(tmp_path, full_model(), mode="lazy")
    assert run_trace(ctx, "q", ENTRY, "lazy") == "complete"
    graph = ctx.store.get_graph("t1", 1)
    assert [n.level for n in graph.nodes] == [0, 0]
    phase = graph.nodes[0]
    children = expand_phase(ctx, phase.id)
    assert [c.title for c in children] == ["accept", "queue"]
    again = ctx.store.get_graph("t1", 1)
    assert len(again.nodes) == 4
    assert len(expand_phase(ctx, phase.id)) == 2
    assert len(ctx.store.get_graph("t1", 1).nodes) == 4


def test_expand_unknown_phase_raises(tmp_path: Path) -> None:
    ctx, _ = setup(tmp_path, full_model())
    with pytest.raises(KeyError):
        expand_phase(ctx, "nope")


def test_run_trace_non_git_repo(tmp_path: Path) -> None:
    ctx, _ = setup(tmp_path, full_model(), git=False)
    assert run_trace(ctx, "q", ENTRY, "eager") == "complete"
    trace = ctx.store.get_trace("t1")
    assert trace is not None and trace.commit_sha is None and trace.status == "complete"


def test_run_trace_side_node_for_error_hop(tmp_path: Path) -> None:
    walk = [hop(UPLOAD, ACCEPT, "h1"), hop(ACCEPT, ERR, "h2", kind="error"), submit(done=True)]
    steps = {"only": submit(steps=[step_draft("accept", [ACCEPT])])}
    phases = submit(phases=[phase_draft(0, 1, "only")])
    ctx, _ = setup(tmp_path, RoutedModel(walk, phases, steps))
    assert run_trace(ctx, "q", ENTRY, "eager") == "complete"
    graph = ctx.store.get_graph("t1", 1)
    side = [n for n in graph.nodes if n.title == "insert"]
    assert len(side) == 1 and side[0].level == 1
    assert any(e.kind == "error" and e.target_id == side[0].id for e in graph.edges)


def test_run_trace_single_function_flow(tmp_path: Path) -> None:
    phases = submit(phases=[phase_draft(0, 0, "only")])
    steps = {"only": submit(steps=[step_draft("Accept the upload (upload)", [UPLOAD])])}
    ctx, _ = setup(tmp_path, RoutedModel([submit(done=True)], phases, steps))
    assert run_trace(ctx, "q", ENTRY, "eager") == "complete"
    assert len([n for n in ctx.store.get_graph("t1", 0).nodes]) == 1


def test_run_trace_walk_partial_keeps_hops(tmp_path: Path) -> None:
    class Boom(RoutedModel):
        def respond(self, **kw: Any) -> Any:
            if not self.walk:
                if kw["system"] in (prompt("split_phases"), prompt("split_steps")):
                    return super().respond(**kw)
                raise ModelError("429")
            return super().respond(**kw)

    walk = [hop(UPLOAD, ACCEPT, "h1")]
    phases = submit(phases=[phase_draft(0, 1, "only")])
    steps = {"only": submit(steps=[step_draft("accept", [ACCEPT])])}
    ctx, events = setup(tmp_path, Boom(walk, phases, steps))
    assert run_trace(ctx, "q", ENTRY, "eager") == "partial"
    assert len(ctx.store.get_hops("t1")) == 1
    assert "429" in events[-1].message
    trace = ctx.store.get_trace("t1")
    assert trace is not None and trace.status == "partial"


def test_run_trace_split_failure_is_partial(tmp_path: Path) -> None:
    class StepsFail(RoutedModel):
        def respond(self, **kw: Any) -> Any:
            if kw["system"] == prompt("split_steps"):
                raise ModelError("boom")
            return super().respond(**kw)

    ctx, _ = setup(tmp_path, StepsFail(FULL_WALK, PHASES, STEPS))
    assert run_trace(ctx, "q", ENTRY, "eager") == "partial"
    assert len(ctx.store.get_graph("t1", 1).nodes) == 2


def test_run_trace_failed_when_nothing_survives(tmp_path: Path) -> None:
    class Dead:
        def respond(self, **_: Any) -> ModelResponse:
            raise ModelError("down")

    ctx, events = setup(tmp_path, Dead())
    assert run_trace(ctx, "q", ENTRY, "eager") == "failed"
    trace = ctx.store.get_trace("t1")
    assert trace is not None and trace.status == "failed"
    assert events[-1].kind == "finished" and events[-1].data == {"status": "failed"}


def test_run_trace_eager_concurrency_4(tmp_path: Path) -> None:
    anchors = [UPLOAD, ACCEPT, ENQUEUE, PARSE, STORE]
    names = ["p0", "p1", "p2", "p3", "p4"]
    phases = submit(phases=[phase_draft(i, i, n) for i, n in enumerate(names)])
    steps = {
        n: submit(steps=[step_draft(f"s-{n}", [a])]) for n, a in zip(names, anchors, strict=True)
    }
    walk = [
        hop(UPLOAD, ACCEPT, "h1"),
        hop(UPLOAD, ENQUEUE, "h2"),
        hop(ENQUEUE, PARSE, "h3", kind="async", hop_type="indirect"),
        resp(tool_use("submit", {"verdict": "confirmed", "evidence": "HANDLERS"}, "v")),
        hop(PARSE, STORE, "h4"),
        submit(done=True),
    ]

    class Locked(RoutedModel):
        lock = threading.Lock()

        def respond(self, **kw: Any) -> Any:
            with self.lock:
                return super().respond(**kw)

    ctx, _ = setup(tmp_path, Locked(walk, phases, steps))
    assert ctx.settings.split_concurrency == 4
    assert run_trace(ctx, "q", ENTRY, "eager") == "complete"
    graph = ctx.store.get_graph("t1", 1)
    assert len([n for n in graph.nodes if n.level == 0]) == 5
    assert len([n for n in graph.nodes if n.level == 1]) == 5


def test_run_trace_warns_about_unreachable_hops(tmp_path: Path) -> None:
    walk = [hop(UPLOAD, ACCEPT, "h1"), hop(PARSE, STORE, "h2"), submit(done=True)]
    steps = {"only": submit(steps=[step_draft("accept", [ACCEPT])])}
    phases = submit(phases=[phase_draft(0, 1, "only")])
    ctx, events = setup(tmp_path, RoutedModel(walk, phases, steps))
    run_trace(ctx, "q", ENTRY, "eager")
    lost = [e.message for e in events if e.kind == "warning" and "not reachable" in e.message]
    assert len(lost) == 1 and "parse_document" in lost[0]
