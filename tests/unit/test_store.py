import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codemap.agents.model import ModelResponse
from codemap.domain.events import Event
from codemap.domain.models import (
    Anchor,
    Edge,
    Effect,
    ExplainStep,
    Hop,
    IoSide,
    Node,
    NodeExplain,
    Trace,
    VerifierResult,
)
from codemap.repo.index import Symbol
from codemap.store.caches import SqliteCallCache, SqliteSymbolCache, SqliteVerdictCache
from codemap.store.db import SCHEMA_VERSION, SchemaTooNewError, _pending, migrate, open_db
from codemap.store.traces import TraceStore

WORKER = Path(__file__).parent.parent / "fixtures/sample_repo/app/worker.py"


def anchor(symbol: str = "parse_document") -> Anchor:
    return Anchor(file="app/worker.py", start_line=9, end_line=13, symbol=symbol, content_hash="h")


def make_trace(trace_id: str = "t1", minute: int = 0) -> Trace:
    return Trace(
        id=trace_id, question="q", entry=anchor(), commit_sha=None, dirty=False,
        status="running", mode="eager", model="m",
        created_at=datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
    )  # fmt: skip


def make_node(node_id: str, level: int, parent: str | None, order: int = 0) -> Node:
    return Node(
        id=node_id, level=level, parent_id=parent, order=order, title=node_id, does="d",
        input="i", output="o", boundary_reason="b", anchors=(anchor(),),
        effects=(Effect(category="object_store", target="s3", op="write", anchor=anchor()),),
        warnings=("w",),
    )  # fmt: skip


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return open_db(tmp_path / "sub" / "codemap.db")


@pytest.fixture
def store(conn: sqlite3.Connection) -> TraceStore:
    s = TraceStore(conn)
    s.create_trace(make_trace())
    return s


def seed_graph(store: TraceStore) -> None:
    nodes = [
        make_node("p1", 0, None),
        make_node("s1", 1, "p1", 0),
        make_node("s2", 1, "p1", 1),
    ]
    store.save_nodes("t1", nodes, [Edge(source_id="s1", target_id="s2", kind="call")])


def test_migrate_sets_version(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    migrate(conn)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_schema_too_new(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA user_version=99")
    with pytest.raises(SchemaTooNewError):
        migrate(conn)


def test_trace_roundtrip_and_totals(store: TraceStore) -> None:
    store.create_trace(make_trace("t2", 5))
    store.set_totals("t1", 3, 4, 0.5)
    store.set_status("t1", "complete")
    got = store.get_trace("t1")
    assert got is not None
    assert (got.input_tokens, got.output_tokens, got.cost_usd, got.status) == (
        3,
        4,
        0.5,
        "complete",
    )
    assert [t.id for t in store.list_traces()] == ["t2", "t1"]
    assert store.get_trace("none") is None


def test_graph_roundtrip_depth(store: TraceStore) -> None:
    seed_graph(store)
    top = store.get_graph("t1", 0)
    assert len(top.nodes) == 1 and top.edges == ()
    full = store.get_graph("t1", 1)
    assert [n.id for n in full.nodes] == ["p1", "s1", "s2"]
    assert len(full.edges) == 1
    assert full.nodes[1] == make_node("s1", 1, "p1", 0)
    assert store.get_node("t1", "s2") == make_node("s2", 1, "p1", 1)
    with pytest.raises(KeyError):
        store.get_graph("nope", 1)


def test_replace_children(store: TraceStore) -> None:
    seed_graph(store)
    store.save_nodes(
        "t1", [make_node("c1", 2, "s1")], [Edge(source_id="c1", target_id="s2", kind="call")]
    )
    store.replace_children("t1", "p1", [make_node("n1", 1, "p1")], [])
    graph = store.get_graph("t1", 5)
    assert [n.id for n in graph.nodes] == ["p1", "n1"]
    assert graph.edges == ()


def test_set_stale(store: TraceStore) -> None:
    seed_graph(store)
    store.set_stale("t1", {"s1"})
    node = store.get_node("t1", "s1")
    assert node is not None and node.stale


def test_hops_and_effects(store: TraceStore) -> None:
    hop = Hop(id="h1", caller=anchor(), callee=anchor("ocr"), kind="call", hop_type="direct")
    store.save_hops("t1", [hop])
    assert store.get_hops("t1") == [hop]
    effect = Effect(category="db", target="pages", op="write", anchor=anchor())
    store.save_walk_effects("t1", [effect])
    assert store.get_walk_effects("t1") == [effect]


def test_events_after(store: TraceStore) -> None:
    def event(msg: str) -> Event:
        return Event(
            trace_id="t1", kind="warning", message=msg, at=datetime(2026, 1, 1, tzinfo=UTC)
        )

    first = store.add_event(event("a"))
    second = store.add_event(event("b"))
    assert second > first
    assert [e.message for _, e in store.events_after("t1", 0)] == ["a", "b"]
    assert [i for i, _ in store.events_after("t1", first)] == [second]


def test_mark_running_partial(store: TraceStore) -> None:
    store.create_trace(make_trace("t2"))
    store.set_status("t2", "complete")
    assert store.mark_running_partial() == 1
    got = store.get_trace("t1")
    assert got is not None and got.status == "partial"


def test_no_source_text_stored(conn: sqlite3.Connection, store: TraceStore) -> None:
    seed_graph(store)
    store.save_hops(
        "t1", [Hop(id="h1", caller=anchor(), callee=anchor("ocr"), kind="call", hop_type="direct")]
    )
    lines = [x.strip() for x in WORKER.read_text().splitlines() if len(x.strip()) > 8]
    assert any("s3.put(" in x for x in lines)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608
            for value in row:
                if isinstance(value, str):
                    assert not any(line in value for line in lines), (table, value)


def test_call_cache_roundtrip(conn: sqlite3.Connection) -> None:
    cache = SqliteCallCache(conn)
    resp = ModelResponse(content=[{"type": "text", "text": "hi"}], stop_reason="end_turn",
                         input_tokens=1, output_tokens=2)  # fmt: skip
    assert cache.get("k") is None
    cache.put("k", resp)
    assert cache.get("k") == resp


def test_symbol_and_verdict_caches(conn: sqlite3.Connection) -> None:
    symbols = SqliteSymbolCache(conn)
    items = [Symbol(name="f", kind="function", start_line=1, end_line=2, signature="def f()")]
    assert symbols.get("h") is None
    symbols.put("h", items)
    assert symbols.get("h") == items
    verdicts = SqliteVerdictCache(conn)
    result = VerifierResult(verdict="rejected", evidence="e", suggested_callee=anchor())
    verdicts.put("v", result)
    assert verdicts.get("v") == result
    assert verdicts.get("x") is None


def _schema1_db(path: Path) -> None:
    """Build a real schema-1 file by running 0001 only, then add old-style rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    sql = next(s for n, s in _pending(0) if n == 1)
    raw.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version=1;\nCOMMIT;")
    a = anchor().model_dump(mode="json")
    old = [
        {"category": "db", "target": "t", "op": op, "fields": [], "anchor": a}
        for op in ("publish", "call", "delete", "consume")
    ]
    raw.execute(
        "INSERT INTO traces VALUES ('t1','q',?,NULL,0,'complete','eager','2026-01-01','m',0,0,0)",
        (anchor().model_dump_json(),),
    )
    raw.execute(
        "INSERT INTO nodes VALUES ('t1','n1',0,NULL,0,'T','d','i','o','b',?,?,NULL,0,'[]')",
        (json.dumps([a]), json.dumps(old)),
    )
    raw.execute(
        "INSERT INTO walk_effects (trace_id, effect) VALUES ('t1', ?)", (json.dumps(old[0]),)
    )
    raw.commit()
    raw.close()


def test_migrate_v1_db_to_v2(tmp_path: Path) -> None:
    db = tmp_path / "old" / "codemap.db"
    _schema1_db(db)
    conn = open_db(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    store = TraceStore(conn)
    node = store.get_node("t1", "n1")
    assert node is not None
    assert node.summary == ""
    assert [e.op for e in node.effects] == ["write", "read", "write", "read"]
    assert [e.op for e in store.get_walk_effects("t1")] == ["write"]
    assert store.get_explain("t1", "n1") is None


def test_failed_post_step_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from codemap.store import db as db_module

    db = tmp_path / "old" / "codemap.db"
    _schema1_db(db)

    def boom(_conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("boom")

    monkeypatch.setitem(db_module._POST, 2, boom)
    with pytest.raises(sqlite3.OperationalError):
        open_db(db)
    raw = sqlite3.connect(db)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "summary" not in [r[1] for r in raw.execute("PRAGMA table_info(nodes)")]


def test_explain_roundtrip(store: TraceStore) -> None:
    seed_graph(store)
    assert store.get_explain("t1", "s1") is None
    explain = NodeExplain(
        steps=(ExplainStep(text="Parses the file", lines=(9, 12), file="app/worker.py"),),
        input=IoSide(type="bytes", fields=("body",), node_id="p0"),
        output=IoSide(type="Doc"),
    )
    store.save_explain("t1", "s1", explain)
    assert store.get_explain("t1", "s1") == explain
    store.save_explain("t1", "s1", NodeExplain())
    assert store.get_explain("t1", "s1") == NodeExplain()


def test_summary_roundtrip(store: TraceStore) -> None:
    node = make_node("p1", 0, None).model_copy(update={"summary": "Parses uploads."})
    store.save_nodes("t1", [node], [])
    got = store.get_node("t1", "p1")
    assert got is not None and got.summary == "Parses uploads."


def test_graph_depth_3(store: TraceStore) -> None:
    chain = [make_node(f"n{i}", i, f"n{i - 1}" if i else None) for i in range(5)]
    store.save_nodes("t1", chain, [])
    assert [n.id for n in store.get_graph("t1", 3).nodes] == ["n0", "n1", "n2", "n3"]
    assert len(store.get_graph("t1", 9).nodes) == 5
