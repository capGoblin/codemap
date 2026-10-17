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
    Hop,
    Node,
    Trace,
    VerifierResult,
)
from codemap.repo.index import Symbol
from codemap.store.caches import SqliteCallCache, SqliteSymbolCache, SqliteVerdictCache
from codemap.store.db import SCHEMA_VERSION, SchemaTooNewError, migrate, open_db
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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1
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
