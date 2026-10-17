import shutil
from pathlib import Path
from typing import Any

from codemap.agents.limits import Limits
from codemap.agents.model import ModelError
from codemap.domain.models import Anchor, Effect, Hop, Node
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.split import (
    phase_code,
    phase_edges,
    side_nodes,
    split_phases,
    split_steps,
    steps_edges,
)
from codemap.settings import Settings
from fakes import ScriptedModel, resp, tool_use

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


def a(file: str, start: int, end: int, symbol: str) -> Anchor:
    return Anchor(file=file, start_line=start, end_line=end, symbol=symbol)


UPLOAD = a("app/api.py", 5, 8, "upload")
ACCEPT = a("app/documents.py", 12, 14, "accept_document")
ENQUEUE = a("app/queue.py", 6, 7, "enqueue")
PARSE = a("app/worker.py", 9, 12, "parse_document")
STORE = a("app/storage.py", 4, 5, "store_pages")
POINTS = [UPLOAD, ACCEPT, ENQUEUE, PARSE, STORE]

DB_WRITE = Effect(
    category="db", target="document", op="write", anchor=a("app/documents.py", 13, 13, "insert")
)
S3_WRITE = Effect(
    category="object_store",
    target="normalized/{doc_id}",
    op="write",
    anchor=a("app/worker.py", 11, 11, "put"),
)
EFFECTS = [DB_WRITE, S3_WRITE]


def make_ctx(tmp_path: Path, model: Any) -> TraceContext:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return build_context(repo, Settings(), "t1", model=model)


def phase_draft(start: int, end: int, title: str) -> dict[str, Any]:
    return {
        "title": title,
        "does": "does",
        "input": "in",
        "output": "out",
        "boundary_reason": "why",
        "start": start,
        "end": end,
    }


def submit(**fields: Any) -> Any:
    return resp(tool_use("submit", fields, "s1"))


def node(id: str, level: int, order: int, anchors: tuple[Anchor, ...], **kw: Any) -> Node:
    return Node(
        id=id,
        level=level,
        parent_id=kw.pop("parent_id", None),
        order=order,
        title=id,
        does="",
        input="",
        output="",
        boundary_reason="",
        anchors=anchors,
        **kw,
    )


def test_split_phases_span_validation_retry(tmp_path: Path) -> None:
    gap = submit(phases=[phase_draft(0, 1, "A"), phase_draft(3, 4, "B")])
    good = submit(phases=[phase_draft(0, 2, "intake"), phase_draft(3, 4, "worker")])
    model = ScriptedModel([gap, good])
    ctx = make_ctx(tmp_path, model)
    phases, reason = split_phases(ctx, "q", POINTS, EFFECTS)
    assert reason is None
    assert [p.title for p in phases] == ["intake", "worker"]
    assert phases[0].anchors == tuple(POINTS[0:3])
    assert phases[1].anchors == tuple(POINTS[3:5])
    assert [(p.level, p.parent_id, p.order) for p in phases] == [(0, None, 0), (0, None, 1)]
    assert phases[0].effects == (DB_WRITE,)
    assert phases[1].effects == (S3_WRITE,)
    assert len({p.id for p in phases}) == 2
    # the retry message carried the error
    assert "validation error" in str(model.requests[1]["messages"][-1]["content"])
    user = model.requests[0]["messages"][0]["content"]
    assert "0: app/api.py:5-8 upload" in user
    assert "4: app/storage.py:4-5 store_pages" in user


def test_split_phases_must_cover_all_points(tmp_path: Path) -> None:
    short = submit(phases=[phase_draft(0, 3, "A")])
    good = submit(phases=[phase_draft(0, 4, "A")])
    ctx = make_ctx(tmp_path, ScriptedModel([short, good]))
    phases, reason = split_phases(ctx, "q", POINTS, EFFECTS)
    assert reason is None and len(phases) == 1


def test_split_phases_model_error_returns_reason(tmp_path: Path) -> None:
    class Failing:
        def respond(self, **_: Any) -> Any:
            raise ModelError("boom")

    ctx = make_ctx(tmp_path, Failing())
    assert split_phases(ctx, "q", POINTS, EFFECTS) == ([], "boom")


def step_draft(title: str, anchors: list[Anchor], group: int | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "does": "does",
        "input": "in",
        "output": "out",
        "boundary_reason": "why",
        "anchors": [x.model_dump() for x in anchors],
        "parallel_group": group,
    }


def test_split_steps_drops_outside_anchor(tmp_path: Path) -> None:
    stray = a("app/unused.py", 1, 3, "legacy_upload")
    model = ScriptedModel(
        [
            submit(
                steps=[
                    step_draft("accept", [ACCEPT, stray]),
                    step_draft("ghost", [stray]),
                    step_draft("queue", [ENQUEUE]),
                ]
            )
        ]
    )
    ctx = make_ctx(tmp_path, model)
    phase = node("p0", 0, 0, (UPLOAD, ACCEPT, ENQUEUE))
    steps, reason = split_steps(ctx, phase, EFFECTS)
    assert reason is None
    assert [s.title for s in steps] == ["accept", "queue"]
    assert steps[0].anchors[0].file == "app/documents.py"
    assert steps[0].anchors[0].content_hash
    assert [(s.level, s.parent_id, s.order) for s in steps] == [(1, "p0", 0), (1, "p0", 1)]
    assert steps[0].effects == (DB_WRITE,)
    assert steps[1].effects == ()
    user = model.requests[0]["messages"][0]["content"]
    assert "0: app/api.py:5-8 upload" in user
    assert [t["name"] for t in model.requests[0]["tools"]] == ["submit"]
    assert "6: " in user and "accept_document(request.file)" in user


def test_split_steps_limit_returns_reason(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ScriptedModel([]))
    ctx.budget._limits = Limits(wall_seconds=1, max_tokens=0, max_cost_usd=1.0, max_tool_calls=1)
    phase = node("p0", 0, 0, (UPLOAD,))
    steps, reason = split_steps(ctx, phase, EFFECTS)
    assert steps == [] and reason


def test_split_steps_empty_submit_is_not_a_failure(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ScriptedModel([submit(steps=[])]))
    assert split_steps(ctx, node("p0", 0, 0, (UPLOAD,)), []) == ([], None)


def test_steps_edges_sequential_and_parallel() -> None:
    def s(id: str, order: int, group: int | None = None) -> Node:
        return node(id, 1, order, (UPLOAD,), parallel_group=group)

    steps = [s("a", 0), s("b", 1, 1), s("c", 2, 1), s("d", 3)]
    edges = {(e.source_id, e.target_id, e.kind) for e in steps_edges(steps)}
    assert edges == {
        ("a", "b", "call"),
        ("a", "c", "call"),
        ("b", "d", "call"),
        ("c", "d", "call"),
    }
    assert steps_edges(steps[:1]) == []


def hop(caller: Anchor, callee: Anchor, kind: str = "call") -> Hop:
    return Hop(
        id="h",
        caller=caller,
        callee=callee,
        kind=kind,  # type: ignore[arg-type]
        hop_type="direct",
        verdict="code_checked",
    )


def test_phase_edges_async_when_crossing_hop_is_async() -> None:
    p0 = node("p0", 0, 0, (UPLOAD, ACCEPT, ENQUEUE))
    p1 = node("p1", 0, 1, (PARSE,))
    p2 = node("p2", 0, 2, (STORE,))
    hops = [
        hop(UPLOAD, ACCEPT),
        hop(ENQUEUE, PARSE, "async"),
        hop(PARSE, STORE),
    ]
    edges = {(e.source_id, e.target_id, e.kind) for e in phase_edges([p0, p1, p2], hops)}
    assert edges == {("p0", "p1", "async"), ("p1", "p2", "call")}


def test_side_nodes_attach_to_containing_node() -> None:
    err = a("app/errors.py", 1, 2, "on_fail")
    branch = a("app/branch.py", 3, 4, "alt")
    phase = node("p0", 0, 0, (UPLOAD, ACCEPT))
    step = node("s0", 1, 0, (ACCEPT,), parent_id="p0")
    side = [hop(ACCEPT, err, "error"), hop(UPLOAD, branch, "branch")]
    new_nodes, edges = side_nodes(side, [phase, step])
    by_title = {n.title: n for n in new_nodes}
    assert by_title["on_fail"].level == 1 and by_title["on_fail"].parent_id == "p0"
    assert by_title["alt"].level == 0 and by_title["alt"].parent_id is None
    assert by_title["on_fail"].anchors == (err,)
    got = {(e.source_id, e.target_id, e.kind) for e in edges}
    assert (step.id, by_title["on_fail"].id, "error") in got
    assert (phase.id, by_title["alt"].id, "branch") in got


def test_side_nodes_skip_hop_with_no_container() -> None:
    other = hop(a("app/unused.py", 1, 3, "legacy_upload"), a("app/x.py", 1, 1, "x"), "error")
    assert side_nodes([other], [node("p0", 0, 0, (UPLOAD,))]) == ([], [])


def test_split_steps_sends_code_inline_and_gives_no_read_tools(tmp_path: Path) -> None:
    model = ScriptedModel([submit(steps=[step_draft("Accept the file (upload)", [UPLOAD])])])
    ctx = make_ctx(tmp_path, model)
    steps, reason = split_steps(ctx, node("p0", 0, 0, (UPLOAD,)), [])
    assert reason is None and len(steps) == 1
    user = model.requests[0]["messages"][0]["content"]
    assert "5: def upload(request):" in user
    assert [t["name"] for t in model.requests[0]["tools"]] == ["submit"]


def test_split_steps_stops_after_four_turns(tmp_path: Path) -> None:
    chatter = resp({"type": "text", "text": "thinking"}, stop="end_turn")
    model = ScriptedModel([chatter] * 6)
    ctx = make_ctx(tmp_path, model)
    steps, reason = split_steps(ctx, node("p0", 0, 0, (UPLOAD,)), [])
    assert steps == [] and reason == "max_turns"
    assert len(model.requests) == 4


def test_phase_code_over_cap_sends_signatures_and_heads(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    body = "\n".join(f"    x{i} = {i}" for i in range(1000))
    (repo / "big.py").write_text(f"def big():\n{body}\n")
    ctx = build_context(repo, Settings(), "t1", model=ScriptedModel([]))
    phase = node("p0", 0, 0, (a("big.py", 1, 1001, "big"),))
    text = phase_code(ctx.tools, phase)
    assert "1: def big():" in text and "40: " in text and "41: " not in text
    assert "first 40 of 1001 lines" in text
    assert "big.py:1-1001 function_definition big" in text


def test_split_steps_rejects_bare_function_name_title(tmp_path: Path) -> None:
    bare = submit(steps=[step_draft("upload", [UPLOAD])])
    good = submit(steps=[step_draft("Accept the file (upload)", [UPLOAD])])
    model = ScriptedModel([bare, good])
    ctx = make_ctx(tmp_path, model)
    steps, reason = split_steps(ctx, node("p0", 0, 0, (UPLOAD,)), [])
    assert reason is None and [s.title for s in steps] == ["Accept the file (upload)"]
    assert "only the function name" in str(model.requests[1]["messages"][-1]["content"])


def test_split_phases_rejects_bare_function_name_title(tmp_path: Path) -> None:
    bare = submit(phases=[phase_draft(0, 4, "upload")])
    good = submit(phases=[phase_draft(0, 4, "Upload and parse (upload)")])
    model = ScriptedModel([bare, good])
    ctx = make_ctx(tmp_path, model)
    phases, reason = split_phases(ctx, "q", POINTS, EFFECTS)
    assert reason is None and phases[0].title == "Upload and parse (upload)"
    err = str(model.requests[1]["messages"][-1]["content"])
    assert "only the function name" in err and "Rule" in err
