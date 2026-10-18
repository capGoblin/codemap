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


def node(
    id: str,
    level: int,
    parent: str | None,
    order: int,
    *anchors: Anchor,
    effects=(),
    summary="ok",
    title=None,
):
    return Node(
        id=id,
        level=level,
        parent_id=parent,
        order=order,
        title=title or id,
        summary=summary,
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


def deep_expected() -> ExpectedTrace:
    e = expected()
    e.phases[0].steps[0].steps = [ExpectedNode(title="g", spans=[anc("app/api.py", 1, 2)])]
    return e


def deep_nodes() -> list[Node]:
    return [
        *perfect(),
        node("g1", 2, "s1", 0, anc("app/api.py", 1, 2)),
    ]


def test_n_level_perfect_and_depth_recall():
    s = score(graph(*deep_nodes()), deep_expected())
    assert s.step_agreement == 1.0
    assert s.depth_recall == 1.0


def test_n_level_step_agreement_averages_all_parents():
    nodes = [n for n in deep_nodes() if n.id != "g1"]
    nodes.append(node("g1", 2, "s1", 0, anc("app/other.py", 1, 2)))
    s = score(graph(*nodes), deep_expected())
    # parents p1 (1.0), p2 (leaf, skipped), s1 (0.0): mean 0.5
    assert s.step_agreement == 0.5


def test_depth_recall_counts_any_deeper_level():
    nodes = [n for n in deep_nodes() if n.id != "g1"]
    s = score(graph(*nodes), deep_expected())
    # s1 spans app/api.py 1-4 and overlaps the expected level-2 span
    assert s.depth_recall == 1.0
    phases_only = [n for n in nodes if n.level == 0]
    assert score(graph(*phases_only), deep_expected()).depth_recall == 0.0


def test_max_phases_ok():
    many = [node(f"p{i}", 0, None, i, anc("app/api.py", 1, 8)) for i in range(8)]
    assert score(graph(*many), expected()).max_phases_ok is False
    assert score(graph(*perfect()), expected()).max_phases_ok is True


def test_titles_ok():
    long = node("p1", 0, None, 0, anc("app/api.py", 1, 8), title="one two three four five")
    assert score(graph(long), expected()).titles_ok is False
    assert score(graph(*perfect()), expected()).titles_ok is True


def test_summaries_ok():
    empty = node("p1", 0, None, 0, anc("app/api.py", 1, 8), summary="")
    wordy = node("p1", 0, None, 0, anc("app/api.py", 1, 8), summary=" ".join(["w"] * 15))
    assert score(graph(empty), expected()).summaries_ok is False
    assert score(graph(wordy), expected()).summaries_ok is False
    assert score(graph(*perfect()), expected()).summaries_ok is True


def test_plumbing_phase_titles():
    a = node("p1", 0, None, 0, anc("app/api.py", 1, 8), title="Outbox relay")
    b = node("p2", 0, None, 1, anc("app/worker.py", 1, 12), title="Run workflow")
    c = node("s1", 1, "p1", 0, anc("app/api.py", 1, 4), title="Update status")
    s = score(graph(a, b, c), expected())
    assert s.plumbing_phase_titles == 2
    assert "plumbing_titles=2" in format_score(s)


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parents[1] / "codemap-trace.expected.json"


def test_load_codemap_expected_shape():
    exp = load_expected(GOLDEN, ROOT)
    assert [p.title for p in exp.phases] == [
        "Start trace",
        "Find entry",
        "Walk & verify",
        "Build levels",
        "Validate & save",
    ]
    nodes = []

    def walk(ns):
        for n in ns:
            nodes.append(n)
            walk(n.steps)

    walk(exp.phases)
    assert all(len(n.title.split()) <= 4 for n in nodes)
    assert all(0 < len(n.summary.split()) <= 14 for n in nodes)
    assert {e.op for e in exp.effects} <= {"read", "write"}
    build = [s.title for s in exp.phases[3].steps]
    assert {"Order path points", "Split into phases", "Split into steps"} <= set(build)
