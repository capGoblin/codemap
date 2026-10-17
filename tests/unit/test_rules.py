import pytest

from codemap.domain.models import Anchor, Effect, Hop, Node
from codemap.domain.rules import (
    anchor_contains,
    anchor_key,
    assign_effects,
    callee_named_in,
    drop_ratio,
    io_chain_warning,
    normalize_op,
    normalize_target,
    ordered_points,
    path_points,
    rollup_effects,
    side_hops,
    unreachable_hops,
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


def test_path_points_joins_symbol_spellings_and_ranges():
    """Real failure: Session.build_system as callee, build_system as the next caller."""
    e = anc("s.py", 1, 5, "run")
    callee = anc("chat-agent/session.py", 63, 88, "Session.build_system")
    caller = anc("chat-agent/session.py", 63, 88, "build_system")
    shifted = anc("chat-agent/session.py", 65, 80, "build_system")
    g1, g2 = anc("chat-agent/r.py", 1, 9, "gated_retrieve"), anc("chat-agent/r.py", 20, 30, "should_retrieve")
    points = path_points(e, [hop(e, callee), hop(caller, g1), hop(shifted, g2)])
    assert [p.symbol for p in points] == [
        "run",
        "Session.build_system",
        "gated_retrieve",
        "should_retrieve",
    ]


def test_path_points_does_not_join_other_files_or_disjoint_ranges():
    e = anc("a.py", 1, 5, "e")
    b = anc("a.py", 10, 20, "b")
    other = anc("c.py", 10, 20, "b")
    c = anc("a.py", 30, 40, "c")
    points, bridges = ordered_points(e, [hop(e, b), hop(other, c)])
    assert points == [e, b, other, c]  # c.py "b" is not joined to a.py "b"
    assert [(x.from_anchor, x.to_anchor) for x in bridges] == [(b, other)]


def test_unreachable_hops_lists_dangling():
    from codemap.domain.rules import unreachable_hops

    e, a, x, y = (
        anc("f.py", 1, 5, "e"),
        anc("f.py", 10, 15, "a"),
        anc("f.py", 50, 60, "x"),
        anc("f.py", 70, 80, "y"),
    )
    hops = [hop(e, a), hop(x, y)]
    assert [h.caller.symbol for h in unreachable_hops([e, a], hops)] == ["x"]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("write", "write"), ("delete", "write"), ("publish", "write"),
        ("read", "read"), ("consume", "read"), ("call", "read"),
    ],
)  # fmt: skip
def test_normalize_op_mapping(old: str, new: str) -> None:
    assert normalize_op(old) == new


def test_normalize_op_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        normalize_op("frobnicate")


@pytest.mark.parametrize(
    ("category", "raw", "want"),
    [
        ("db", "FileUpload row", "FileUpload"),
        ("db", "company_intelligence_document table", "company_intelligence_document"),
        ("db", "`documents` rows.", "documents"),
        ("db", "table users", "users"),
        ("object_store", "S3 via DocumentStorage.put", "DocumentStorage"),
        ("object_store", "S3 via DocumentStorage.put()", "DocumentStorage"),
        ("object_store", "s3://acme-docs/uploads/", "acme-docs/uploads/"),
        ("object_store", "normalized/{doc_id}", "normalized/{doc_id}"),
        ("queue", "order-events via publisher.send", "order-events"),
        ("file", "'audit.log'", "audit.log"),
        ("db", "rows", "rows"),
    ],
)  # fmt: skip
def test_normalize_target_cases(category: str, raw: str, want: str) -> None:
    assert normalize_target(category, raw) == want


def test_ordered_points_bridges_three_islands_in_recorded_order():
    e, a = anc("up.py", 1, 5, "upload"), anc("up.py", 10, 15, "submit")
    w, acc = anc("hook.py", 1, 5, "resolve_scan"), anc("hook.py", 10, 15, "accept")
    o, st = anc("relay.py", 1, 5, "dispatch"), anc("relay.py", 10, 15, "start_wf")
    hops = [hop(w, acc), hop(o, st), hop(e, a)]
    points, bridges = ordered_points(e, hops)
    assert [p.symbol for p in points] == [
        "upload", "submit", "resolve_scan", "accept", "dispatch", "start_wf"
    ]  # fmt: skip
    assert [(b.from_anchor.symbol, b.to_anchor.symbol) for b in bridges] == [
        ("submit", "resolve_scan"),
        ("accept", "dispatch"),
    ]
    assert unreachable_hops(points, hops) == []


def test_ordered_points_root_is_caller_that_is_not_a_callee():
    e, a = anc("f.py", 1, 5, "e"), anc("f.py", 10, 15, "a")
    x, y, z = anc("g.py", 1, 5, "x"), anc("g.py", 10, 15, "y"), anc("g.py", 20, 25, "z")
    points, bridges = ordered_points(e, [hop(e, a), hop(y, z), hop(x, y)])
    assert [p.symbol for p in points] == ["e", "a", "x", "y", "z"]
    assert [b.to_anchor.symbol for b in bridges] == ["x"]


def test_ordered_points_connected_path_has_no_bridge():
    e, a, b = anc("f.py", 1, 5, "e"), anc("f.py", 10, 15, "a"), anc("f.py", 20, 25, "b")
    points, bridges = ordered_points(e, [hop(e, a), hop(a, b)])
    assert points == [e, a, b] and bridges == []
