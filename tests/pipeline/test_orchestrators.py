from pathlib import Path
from typing import Any

from codemap.domain.models import Anchor, Effect, Node
from codemap.pipeline.context import build_context
from codemap.pipeline.orchestrators import find_orchestrators, flatten_points
from codemap.pipeline.split import split_children
from codemap.settings import Settings
from fakes import ScriptedModel, resp, tool_use

RUNNER = """\
def run_trace_pipeline(doc, config):
    entries = resolve_entry_points(doc)
    hops = walk_calls(entries, config)
    levels = split_levels(hops)
    return validate_nodes(levels)
"""


def stage(name: str, arg: str) -> str:
    body = "\n".join(f"    step_{i} = {arg}.get({i})" for i in range(8))
    return f"def {name}({arg}):\n{body}\n    return {arg}\n"


FILES = {
    "pipeline/runner.py": RUNNER,
    "pipeline/resolve.py": stage("resolve_entry_points", "doc"),
    "pipeline/walk.py": stage("walk_calls", "tables"),
    "pipeline/split.py": stage("split_levels", "rows"),
    "pipeline/validate.py": stage("validate_nodes", "mapped"),
}


def anchor(file: str, symbol: str) -> Anchor:
    n = len(FILES[file].splitlines())
    return Anchor(file=file, start_line=1, end_line=n, symbol=symbol)


RUN = anchor("pipeline/runner.py", "run_trace_pipeline")
RESOLVE = anchor("pipeline/resolve.py", "resolve_entry_points")
WALK = anchor("pipeline/walk.py", "walk_calls")
SPLIT = anchor("pipeline/split.py", "split_levels")
VALIDATE = anchor("pipeline/validate.py", "validate_nodes")
POINTS = [RUN, RESOLVE, WALK, SPLIT, VALIDATE]


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    return repo


def test_detects_orchestrator_with_four_stage_callees(tmp_path: Path) -> None:
    ctx = build_context(make_repo(tmp_path), Settings(), "t1", model=ScriptedModel([]))
    found = find_orchestrators(ctx.tools, POINTS, [])
    assert [(o.anchor.symbol, [c.symbol for c in o.callees]) for o in found] == [
        ("run_trace_pipeline", [p.symbol for p in POINTS[1:]])
    ]
    flat, _ = flatten_points(ctx.tools, POINTS, [])
    assert flat == POINTS[1:]


def test_function_with_effects_is_not_an_orchestrator(tmp_path: Path) -> None:
    ctx = build_context(make_repo(tmp_path), Settings(), "t1", model=ScriptedModel([]))
    write = Effect(
        category="db",
        target="doc",
        op="write",
        anchor=Anchor(file=RUN.file, start_line=2, end_line=2, symbol="insert"),
    )
    assert find_orchestrators(ctx.tools, POINTS, [write]) == []


def test_stage_function_with_few_calls_is_not_an_orchestrator(tmp_path: Path) -> None:
    ctx = build_context(make_repo(tmp_path), Settings(), "t1", model=ScriptedModel([]))
    assert find_orchestrators(ctx.tools, [RESOLVE, WALK, SPLIT, VALIDATE], []) == []


def draft(title: str, a: Anchor) -> dict[str, Any]:
    return {
        "title": title,
        "does": "does",
        "input": "in",
        "output": "out",
        "boundary_reason": "why",
        "anchors": [a.model_dump()],
    }


def test_orchestrator_with_four_stage_callees_yields_four_children(tmp_path: Path) -> None:
    steps = [
        draft("Resolve entry", RESOLVE),
        draft("Follow calls", WALK),
        draft("Cut into levels", SPLIT),
        draft("Check nodes", VALIDATE),
    ]
    model = ScriptedModel([resp(tool_use("submit", {"steps": steps}, "s1"))])
    ctx = build_context(make_repo(tmp_path), Settings(), "t1", model=model)
    parent = Node(
        id="s1",
        level=1,
        order=0,
        parent_id="p0",
        title="Run trace pipeline",
        does="d",
        input="i",
        output="o",
        boundary_reason="b",
        anchors=(RUN,),
    )
    kids, reason = split_children(ctx, parent, POINTS, [])
    assert reason is None
    assert [k.title for k in kids] == [
        "Resolve entry",
        "Follow calls",
        "Cut into levels",
        "Check nodes",
    ]
    user = model.requests[0]["messages"][0]["content"]
    assert "[resolve] resolve_entry_points" in user
    assert "Orchestrators folded away" in user
    points_block = user.split("Sub-path points:")[1].split("Parent code:")[0]
    assert "run_trace_pipeline" not in points_block
