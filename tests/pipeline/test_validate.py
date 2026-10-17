from pathlib import Path

from codemap.domain.models import Anchor, Edge, Effect, Node
from codemap.pipeline.validate import validate_graph
from codemap.repo.ignore import RepoIgnore
from codemap.repo.tools import RepoTools

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"

UPLOAD = Anchor(file="app/api.py", start_line=5, end_line=8, symbol="upload")
ACCEPT = Anchor(file="app/documents.py", start_line=12, end_line=14, symbol="accept_document")
LEGACY = Anchor(file="app/unused.py", start_line=1, end_line=3, symbol="legacy_upload")
POINTS = [UPLOAD, ACCEPT]


def tools() -> RepoTools:
    return RepoTools(FIXTURE, RepoIgnore(FIXTURE))


def mk(id: str, anchors: tuple[Anchor, ...], level: int = 0, parent: str | None = None,
       order: int = 0, input: str = "i", output: str = "o",
       effects: tuple[Effect, ...] = ()) -> Node:  # fmt: skip
    return Node(
        id=id, level=level, parent_id=parent, order=order, title=f"T{id}", does="",
        input=input, output=output, boundary_reason="", anchors=anchors, effects=effects,
    )  # fmt: skip


def db_write(anchor: Anchor) -> Effect:
    return Effect(category="db", target="document", op="write", anchor=anchor)


def test_validate_drops_off_path_node() -> None:
    nodes = [mk("a", (UPLOAD,)), mk("b", (LEGACY,))]
    edges = [Edge(source_id="a", target_id="b", kind="call")]
    r = validate_graph(tools(), nodes, edges, POINTS)
    assert [n.id for n in r.nodes] == ["a"]
    assert r.edges == []
    assert r.dropped == 1


def test_validate_keeps_step_that_is_subrange_of_point() -> None:
    sub = Anchor(file="app/api.py", start_line=6, end_line=6, symbol="accept_document")
    r = validate_graph(tools(), [mk("s", (sub,), level=1)], [], POINTS)
    assert r.dropped == 0


def test_validate_keeps_node_when_any_anchor_on_path() -> None:
    r = validate_graph(tools(), [mk("a", (LEGACY, UPLOAD))], [], POINTS)
    assert r.dropped == 0
    assert r.nodes[0].anchors == (LEGACY, UPLOAD)


def test_validate_side_node_exempt_from_path_but_needs_valid_anchor() -> None:
    bad = Anchor(file="app/unused.py", start_line=1, end_line=3, symbol="nope")
    nodes = [mk("side", (LEGACY,), level=1), mk("bad", (bad,), level=1)]
    r = validate_graph(tools(), nodes, [], POINTS, side_ids={"side", "bad"})
    assert [n.id for n in r.nodes] == ["side"]
    assert r.dropped == 1


def test_validate_drops_invalid_anchor_and_ghost_file() -> None:
    ghost = Anchor(file="app/ghost.py", start_line=1, end_line=2, symbol="x")
    r = validate_graph(tools(), [mk("g", (ghost,))], [], [ghost])
    assert r.nodes == [] and r.dropped == 1


def test_validate_drops_effect_with_bad_anchor() -> None:
    bad = Anchor(file="app/api.py", start_line=5, end_line=8, symbol="missing")
    good = db_write(UPLOAD)
    r = validate_graph(tools(), [mk("a", (UPLOAD,), effects=(good, db_write(bad)))], [], POINTS)
    assert r.nodes[0].effects == (good,)


def test_validate_phase_drop_drops_steps() -> None:
    nodes = [
        mk("p", (LEGACY,)),
        mk("s1", (LEGACY,), level=1, parent="p"),
        mk("s2", (UPLOAD,), level=1, parent="p"),
        mk("q", (UPLOAD,)),
    ]
    r = validate_graph(tools(), nodes, [], POINTS)
    assert [n.id for n in r.nodes] == ["q"]
    assert r.dropped == 3


def test_validate_rollup_and_io_warning() -> None:
    e1, e2 = db_write(UPLOAD), db_write(ACCEPT)
    nodes = [
        mk("p", (UPLOAD, ACCEPT), input="req", output="done", effects=(e1,)),
        mk("s1", (UPLOAD,), level=1, parent="p", order=0, input="req", output="x", effects=(e1,)),
        mk("s2", (ACCEPT,), level=1, parent="p", order=1, input="x", output="", effects=(e2,)),
    ]  # fmt: skip
    r = validate_graph(tools(), nodes, [], POINTS)
    phase = r.nodes[0]
    assert set(phase.effects) == {e1, e2}
    assert len(phase.warnings) == 1
    assert r.warnings == [f"Tp: {phase.warnings[0]}"]
    assert "last step has no output" in phase.warnings[0]


def test_validate_matching_io_chain_has_no_warning() -> None:
    nodes = [
        mk("p", (UPLOAD,), input="req", output="done"),
        mk("s1", (UPLOAD,), level=1, parent="p", input="request text", output="the result"),
    ]
    r = validate_graph(tools(), nodes, [], POINTS)
    assert r.warnings == [] and r.nodes[0].warnings == ()


def test_validate_keeps_step_subrange_without_parent_symbol() -> None:
    """The model keeps the parent symbol on a sub-range that does not contain the name."""
    sub = Anchor(file="app/api.py", start_line=7, end_line=7, symbol="upload")
    phase = mk("p", (UPLOAD,))
    r = validate_graph(tools(), [phase, mk("s", (sub,), level=1, parent="p")], [], POINTS)
    assert r.dropped == 0 and r.drops == []


def test_validate_records_drop_reasons() -> None:
    sub = Anchor(file="app/api.py", start_line=7, end_line=7, symbol="upload")
    past_end = Anchor(file="app/api.py", start_line=7, end_line=900, symbol="upload")
    bad_symbol = Anchor(file="app/documents.py", start_line=12, end_line=14, symbol="nope")
    nodes = [
        mk("p", (UPLOAD,)),
        mk("off", (LEGACY,), level=1, parent="p"),
        mk("bad", (bad_symbol,), level=1, parent="p"),
        mk("long", (past_end,), level=1, parent="p"),
        mk("ok", (sub,), level=1, parent="p"),
    ]
    r = validate_graph(tools(), nodes, [], POINTS)
    assert r.dropped == 3
    text = "\n".join(r.drops)
    assert "not on the recorded path" in text and "legacy_upload" in text
    assert "symbol nope not found" in text
    assert "is past end" in text
    assert [n.id for n in r.nodes] == ["p", "ok"]


def test_validate_records_orphan_drop() -> None:
    nodes = [mk("p", (LEGACY,)), mk("s", (UPLOAD,), level=1, parent="p")]
    r = validate_graph(tools(), nodes, [], POINTS)
    assert r.dropped == 2
    assert any("parent was dropped" in d for d in r.drops)


def test_phase_keeps_effects_no_step_covers() -> None:
    late = Anchor(file="app/documents.py", start_line=14, end_line=14, symbol="Doc")
    first = Anchor(file="app/documents.py", start_line=13, end_line=13, symbol="insert")
    covered, uncovered = db_write(first), db_write(late)
    phase = mk("p", (ACCEPT,), effects=(covered, uncovered))
    step = mk("s", (first,), level=1, parent="p", effects=(covered,))
    r = validate_graph(tools(), [phase, step], [], POINTS)
    (out,) = [n for n in r.nodes if n.id == "p"]
    assert out.effects == (covered, uncovered)


def test_validate_rollup_is_recursive_and_drop_takes_subtree() -> None:
    inner = Anchor(file="app/documents.py", start_line=13, end_line=13, symbol="accept_document")
    effect = db_write(ACCEPT)
    top = mk("p", (UPLOAD, ACCEPT))
    mid = mk("m", (ACCEPT,), level=1, parent="p")
    leaf = mk("l", (inner,), level=2, parent="m", effects=(effect,))
    r = validate_graph(tools(), [top, mid, leaf], [], POINTS)
    assert {n.id: n.effects for n in r.nodes}["p"] == (effect,)
    assert {n.id: n.effects for n in r.nodes}["m"] == (effect,)
    bad_mid = mk("m", (LEGACY,), level=1, parent="p")
    r = validate_graph(tools(), [top, bad_mid, leaf], [], POINTS)
    assert [n.id for n in r.nodes] == ["p"]
    assert r.dropped == 2
