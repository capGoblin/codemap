import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codemap.domain.models import Anchor, Effect, Node, Trace, TraceGraph
from evals.expected import ExpectedEffect, ExpectedNode, ExpectedTrace, load_expected
from evals.score import format_score, score

REPO = Path(__file__).resolve().parents[2] / "tests/fixtures/sample_repo"


def anc(file: str, a: int, b: int) -> Anchor:
    return Anchor(file=file, start_line=a, end_line=b, symbol="s")


def node(id: str, level: int, parent: str | None, order: int, *anchors: Anchor, effects=()):
    return Node(
        id=id,
        level=level,
        parent_id=parent,
        order=order,
        title=id,
        does="",
        input="",
        output="",
        boundary_reason="",
        anchors=tuple(anchors),
        effects=tuple(effects),
    )


def graph(*nodes: Node, status="complete") -> TraceGraph:
    t = Trace(
        id="t",
        question="q",
        entry=anc("app/api.py", 1, 2),
        commit_sha=None,
        dirty=False,
        status=status,
        mode="eager",
        created_at=datetime.now(UTC),
        model="m",
    )
    return TraceGraph(trace=t, nodes=nodes, edges=())


def expected() -> ExpectedTrace:
    return ExpectedTrace(
        repo="r",
        commit="c",
        question="q",
        entry=anc("app/api.py", 1, 2),
        phases=[
            ExpectedNode(
                title="api",
                spans=[anc("app/api.py", 1, 8)],
                steps=[ExpectedNode(title="a", spans=[anc("app/api.py", 1, 4)])],
            ),
            ExpectedNode(title="worker", spans=[anc("app/worker.py", 1, 12)]),
        ],
        effects=[ExpectedEffect(category="queue", target="jobs", op="write")],
    )


def perfect() -> list[Node]:
    eff = Effect(category="queue", target="jobs", op="write", anchor=anc("app/queue.py", 1, 2))
    return [
        node("p1", 0, None, 0, anc("app/api.py", 1, 8)),
        node("s1", 1, "p1", 0, anc("app/api.py", 1, 4), effects=[eff]),
        node("p2", 0, None, 1, anc("app/worker.py", 1, 12)),
    ]


def test_perfect_match():
    s = score(graph(*perfect()), expected())
    assert s.off_path_nodes == 0
    assert s.phase_agreement == 1.0
    assert s.step_agreement == 1.0
    assert s.effect_recall == 1.0
    assert s.effect_extra == 0
    assert s.status == "complete"
    assert "complete" in format_score(s)


def test_off_path_node_counted():
    extra = node("x", 0, None, 2, anc("app/unused.py", 1, 3))
    s = score(graph(*perfect(), extra), expected())
    assert s.off_path_nodes == 1
    assert s.phase_agreement < 1.0


def test_merged_phases_penalised():
    merged = node("m", 0, None, 0, anc("app/api.py", 1, 8), anc("app/worker.py", 1, 12))
    s = score(graph(merged), expected())
    assert s.phase_agreement < 0.75


def test_effect_extra_and_missing():
    eff = Effect(category="db", target="docs", op="write", anchor=anc("app/db.py", 1, 2))
    g = graph(node("p1", 0, None, 0, anc("app/api.py", 1, 8), effects=[eff]))
    s = score(g, expected())
    assert s.effect_recall == 0.0
    assert s.effect_extra == 1


def test_load_expected_missing_path(tmp_path):
    f = tmp_path / "e.json"
    data = expected().model_dump()
    data["phases"][0]["spans"][0]["file"] = "app/nope.py"
    f.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="app/nope.py"):
        load_expected(f, REPO)


def test_load_expected_ok(tmp_path):
    f = tmp_path / "e.json"
    f.write_text(json.dumps(expected().model_dump()))
    assert load_expected(f, REPO).phases[1].title == "worker"
