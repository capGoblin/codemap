from pathlib import Path
from typing import Any

from codemap.domain.models import Anchor, Effect, Node
from codemap.pipeline.context import build_context
from codemap.pipeline.orchestrators import find_orchestrators, flatten_points
from codemap.pipeline.split import split_children
from codemap.settings import Settings
from fakes import ScriptedModel, resp, tool_use

RUNNER = """\
def run_domain_pipeline(doc, config):
    tables = locate_domain_tables(doc)
    rows = extract_tables(tables, config)
    mapped = map_rows(rows)
    return gate_values(mapped)
"""


def stage(name: str, arg: str) -> str:
    body = "\n".join(f"    step_{i} = {arg}.get({i})" for i in range(8))
    return f"def {name}({arg}):\n{body}\n    return {arg}\n"


FILES = {
    "pipeline/runner.py": RUNNER,
    "pipeline/locate.py": stage("locate_domain_tables", "doc"),
    "pipeline/extraction.py": stage("extract_tables", "tables"),
    "pipeline/mapping.py": stage("map_rows", "rows"),
    "pipeline/write_gate.py": stage("gate_values", "mapped"),
}


def anchor(file: str, symbol: str) -> Anchor:
    n = len(FILES[file].splitlines())
    return Anchor(file=file, start_line=1, end_line=n, symbol=symbol)


RUN = anchor("pipeline/runner.py", "run_domain_pipeline")
LOCATE = anchor("pipeline/locate.py", "locate_domain_tables")
EXTRACT = anchor("pipeline/extraction.py", "extract_tables")
MAP = anchor("pipeline/mapping.py", "map_rows")
GATE = anchor("pipeline/write_gate.py", "gate_values")
POINTS = [RUN, LOCATE, EXTRACT, MAP, GATE]


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
        ("run_domain_pipeline", [p.symbol for p in POINTS[1:]])
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
    assert find_orchestrators(ctx.tools, [LOCATE, EXTRACT, MAP, GATE], []) == []


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
        draft("Locate tables", LOCATE),
        draft("Extract values", EXTRACT),
        draft("Map to statements", MAP),
        draft("Gate mapped values", GATE),
    ]
    model = ScriptedModel([resp(tool_use("submit", {"steps": steps}, "s1"))])
    ctx = build_context(make_repo(tmp_path), Settings(), "t1", model=model)
    parent = Node(
        id="s1",
        level=1,
        order=0,
        parent_id="p0",
        title="Assemble domain artifact",
        does="d",
        input="i",
        output="o",
        boundary_reason="b",
        anchors=(RUN,),
    )
    kids, reason = split_children(ctx, parent, POINTS, [])
    assert reason is None
    assert [k.title for k in kids] == [
        "Locate tables",
        "Extract values",
        "Map to statements",
        "Gate mapped values",
    ]
    user = model.requests[0]["messages"][0]["content"]
    assert "[locate] locate_domain_tables" in user
    assert "Orchestrators folded away" in user
    points_block = user.split("Sub-path points:")[1].split("Parent code:")[0]
    assert "run_domain_pipeline" not in points_block
