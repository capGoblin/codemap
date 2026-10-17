from codemap.domain.models import Anchor, Effect, Hop, Node
from codemap.domain.rules import (
    anchor_contains,
    anchor_key,
    assign_effects,
    callee_named_in,
    drop_ratio,
    io_chain_warning,
    path_points,
    rollup_effects,
    side_hops,
)


def anc(file: str, start: int, end: int, symbol: str = "s", h: str = "") -> Anchor:
    return Anchor(file=file, start_line=start, end_line=end, symbol=symbol, content_hash=h)


def hop(caller: Anchor, callee: Anchor, kind="call", verdict=None) -> Hop:
    return Hop(
        id=f"{caller.symbol}-{callee.symbol}",
        caller=caller,
        callee=callee,
        kind=kind,
        hop_type="direct",
        verdict=verdict,
    )


def node(inp: str, out: str, effects=()) -> Node:
    return Node(
        id="n",
        level=2,
        parent_id=None,
        order=0,
        title="t",
        does="d",
        input=inp,
        output=out,
        boundary_reason="b",
        anchors=(),
        effects=tuple(effects),
    )


def eff(anchor: Anchor) -> Effect:
    return Effect(category="db", target="t", op="read", anchor=anchor)


def test_callee_named_in():
    assert callee_named_in("x = svc.accept_document(f)", "documents.accept_document") is True
    assert callee_named_in("accept_documents()", "accept_document") is False


def test_path_points_order_and_rejected():
    e, a, b, c, d = (anc("f.py", i * 10, i * 10 + 5, n) for i, n in enumerate("EABCD", 1))
    hops = [
        hop(e, a),
        hop(a, b, "async"),
        hop(a, c, verdict="rejected"),
        hop(e, d),
    ]
    assert path_points(e, hops) == [e, a, b, d]


def test_path_points_ignores_content_hash_and_cycles():
    e = anc("f.py", 1, 5, "E")
    a = anc("f.py", 10, 15, "A", "h1")
    a_unhashed = anc("f.py", 10, 15, "A")
    hops = [hop(e, a), hop(a, e)]
    assert path_points(e, hops) == [e, a]
    assert path_points(anc("f.py", 1, 5, "E", "x"), [hop(e, a_unhashed)])[1] == a_unhashed


def test_side_hops():
    e, a = anc("f.py", 1, 2), anc("f.py", 3, 4)
    hops = [hop(e, a), hop(e, a, "error"), hop(e, a, "branch", "rejected")]
    assert [h.kind for h in side_hops(hops)] == ["error"]


def test_anchor_contains():
    assert anchor_contains(anc("a.py", 10, 20), anc("a.py", 12, 12))
    assert not anchor_contains(anc("a.py", 10, 20), anc("b.py", 12, 12))
    assert not anchor_contains(anc("a.py", 10, 20), anc("a.py", 9, 12))


def test_assign_effects_by_file():
    e = eff(anc("a.py", 12, 12))
    assert assign_effects([anc("a.py", 10, 20)], [e]) == (e,)
    assert assign_effects([anc("b.py", 10, 20)], [e]) == ()


def test_rollup_dedupes_in_order():
    e1 = eff(anc("a.py", 12, 12, h="x"))
    e1_same = eff(anc("a.py", 12, 12))
    e2 = eff(anc("a.py", 14, 14))
    assert rollup_effects([node("i", "o", [e1]), node("i", "o", [e1_same, e2])]) == (e1, e2)


def test_io_chain_warning():
    phase = node("Document ", "Result")
    assert io_chain_warning(phase, [node("other words", "x"), node("x", "nope")]) is None
    msg = io_chain_warning(phase, [node(" ", "x"), node("x", "result")])
    assert msg is not None and "input" in msg
    msg = io_chain_warning(phase, [node("document", "x"), node("x", "")])
    assert msg is not None and "output" in msg
    assert io_chain_warning(node("", ""), [node("", ""), node("", "")]) is None
    assert io_chain_warning(phase, []) is None


def test_anchor_key_and_drop_ratio():
    assert anchor_key(anc("a.py", 1, 2, "s", "h")) == ("a.py", 1, 2, "s")
    assert drop_ratio(3, 1) == 0.25
    assert drop_ratio(0, 0) == 0.0
