"""Trace, graph, hop and event storage."""

import functools
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pydantic import TypeAdapter

from codemap.domain.events import Event
from codemap.domain.models import (
    Anchor,
    Edge,
    Effect,
    Hop,
    Node,
    Trace,
    TraceGraph,
    TraceStatus,
)
from codemap.store.db import conn_lock

_ANCHORS = TypeAdapter(tuple[Anchor, ...])
_EFFECTS = TypeAdapter(tuple[Effect, ...])
_STRINGS = TypeAdapter(tuple[str, ...])

_DESCENDANTS = """
WITH RECURSIVE gone(id) AS (
    SELECT id FROM nodes WHERE trace_id = :t AND parent_id = :p
    UNION
    SELECT n.id FROM nodes n JOIN gone g ON n.parent_id = g.id WHERE n.trace_id = :t
)
"""


def _trace_from(row: sqlite3.Row) -> Trace:
    return Trace.model_validate(
        {
            **{k: v for k, v in dict(row).items() if k != "entry"},
            "entry": Anchor.model_validate_json(row["entry"]),
            "dirty": bool(row["dirty"]),
        }
    )


def _node_from(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        level=row["level"],
        parent_id=row["parent_id"],
        order=row["ord"],
        title=row["title"],
        does=row["does"],
        input=row["input"],
        output=row["output"],
        boundary_reason=row["boundary_reason"],
        anchors=_ANCHORS.validate_json(row["anchors"]),
        effects=_EFFECTS.validate_json(row["effects"]),
        parallel_group=row["parallel_group"],
        stale=bool(row["stale"]),
        warnings=_STRINGS.validate_json(row["warnings"]),
    )


def _node_values(trace_id: str, n: Node) -> tuple[object, ...]:
    return (
        trace_id, n.id, n.level, n.parent_id, n.order, n.title, n.does, n.input,
        n.output, n.boundary_reason, _ANCHORS.dump_json(n.anchors).decode(),
        _EFFECTS.dump_json(n.effects).decode(), n.parallel_group, int(n.stale),
        _STRINGS.dump_json(n.warnings).decode(),
    )  # fmt: skip


def _locked[F: Callable[..., Any]](fn: F) -> F:
    """Hold the connection lock for the whole call, so threads share one connection safely."""

    @functools.wraps(fn)
    def wrapper(self: "TraceStore", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class TraceStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = conn_lock(conn)

    @_locked
    def create_trace(self, trace: Trace) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO traces (id, question, entry, commit_sha, dirty, status, mode,"
                " created_at, model, input_tokens, output_tokens, cost_usd)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trace.id, trace.question, trace.entry.model_dump_json(),
                    trace.commit_sha, int(trace.dirty), trace.status, trace.mode,
                    trace.created_at.isoformat(), trace.model, trace.input_tokens,
                    trace.output_tokens, trace.cost_usd,
                ),
            )  # fmt: skip

    @_locked
    def set_status(self, trace_id: str, status: TraceStatus) -> None:
        with self._conn:
            self._conn.execute("UPDATE traces SET status = ? WHERE id = ?", (status, trace_id))

    @_locked
    def set_totals(
        self, trace_id: str, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE traces SET input_tokens = ?, output_tokens = ?, cost_usd = ? WHERE id = ?",
                (input_tokens, output_tokens, cost_usd, trace_id),
            )

    @_locked
    def get_trace(self, trace_id: str) -> Trace | None:
        row = self._conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
        return _trace_from(row) if row else None

    @_locked
    def list_traces(self) -> list[Trace]:
        rows = self._conn.execute("SELECT * FROM traces ORDER BY created_at DESC, rowid DESC")
        return [_trace_from(r) for r in rows]

    @_locked
    def save_hops(self, trace_id: str, hops: Iterable[Hop]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM hops WHERE trace_id = ?", (trace_id,))
            self._conn.executemany(
                "INSERT INTO hops (trace_id, hop) VALUES (?, ?)",
                [(trace_id, h.model_dump_json()) for h in hops],
            )

    @_locked
    def add_hop(self, trace_id: str, hop: Hop) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO hops (trace_id, hop) VALUES (?, ?)", (trace_id, hop.model_dump_json())
            )

    @_locked
    def get_hops(self, trace_id: str) -> list[Hop]:
        rows = self._conn.execute(
            "SELECT hop FROM hops WHERE trace_id = ? ORDER BY seq", (trace_id,)
        )
        return [Hop.model_validate_json(r[0]) for r in rows]

    @_locked
    def save_walk_effects(self, trace_id: str, effects: Iterable[Effect]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM walk_effects WHERE trace_id = ?", (trace_id,))
            self._conn.executemany(
                "INSERT INTO walk_effects (trace_id, effect) VALUES (?, ?)",
                [(trace_id, e.model_dump_json()) for e in effects],
            )

    @_locked
    def add_walk_effect(self, trace_id: str, effect: Effect) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO walk_effects (trace_id, effect) VALUES (?, ?)",
                (trace_id, effect.model_dump_json()),
            )

    @_locked
    def get_walk_effects(self, trace_id: str) -> list[Effect]:
        rows = self._conn.execute(
            "SELECT effect FROM walk_effects WHERE trace_id = ? ORDER BY seq", (trace_id,)
        )
        return [Effect.model_validate_json(r[0]) for r in rows]

    @_locked
    def get_node(self, trace_id: str, node_id: str) -> Node | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE trace_id = ? AND id = ?", (trace_id, node_id)
        ).fetchone()
        return _node_from(row) if row else None

    def _insert(self, trace_id: str, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO nodes (trace_id, id, level, parent_id, ord, title, does,"
            " input, output, boundary_reason, anchors, effects, parallel_group, stale, warnings)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_node_values(trace_id, n) for n in nodes],
        )
        self._conn.executemany(
            "INSERT OR IGNORE INTO edges (trace_id, source_id, target_id, kind)"
            " VALUES (?, ?, ?, ?)",
            [(trace_id, e.source_id, e.target_id, e.kind) for e in edges],
        )

    @_locked
    def save_nodes(self, trace_id: str, nodes: Sequence[Node], edges: Sequence[Edge]) -> None:
        with self._conn:
            self._insert(trace_id, nodes, edges)

    @_locked
    def replace_graph(self, trace_id: str, nodes: Sequence[Node], edges: Sequence[Edge]) -> None:
        """Swap every node and edge of a trace for these, in one transaction."""
        with self._conn:
            self._conn.execute("DELETE FROM edges WHERE trace_id = ?", (trace_id,))
            self._conn.execute("DELETE FROM nodes WHERE trace_id = ?", (trace_id,))
            self._insert(trace_id, nodes, edges)

    @_locked
    def replace_children(
        self, trace_id: str, parent_id: str, nodes: Sequence[Node], edges: Sequence[Edge]
    ) -> None:
        args = {"t": trace_id, "p": parent_id}
        with self._conn:
            self._conn.execute(
                _DESCENDANTS + "DELETE FROM edges WHERE trace_id = :t AND"
                " (source_id IN (SELECT id FROM gone) OR target_id IN (SELECT id FROM gone))",
                args,
            )
            self._conn.execute(
                _DESCENDANTS + "DELETE FROM nodes WHERE trace_id = :t AND id IN"
                " (SELECT id FROM gone)",
                args,
            )
            self._insert(trace_id, nodes, edges)

    @_locked
    def get_graph(self, trace_id: str, depth: int) -> TraceGraph:
        trace = self.get_trace(trace_id)
        if trace is None:
            raise KeyError(trace_id)
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE trace_id = ? AND level <= ? ORDER BY level, parent_id, ord",
            (trace_id, depth),
        )
        nodes = tuple(_node_from(r) for r in rows)
        ids = {n.id for n in nodes}
        edge_rows = self._conn.execute(
            "SELECT source_id, target_id, kind FROM edges WHERE trace_id = ?"
            " ORDER BY source_id, target_id, kind",
            (trace_id,),
        )
        edges = tuple(
            Edge(source_id=r[0], target_id=r[1], kind=r[2])
            for r in edge_rows
            if r[0] in ids and r[1] in ids
        )
        return TraceGraph(trace=trace, nodes=nodes, edges=edges)

    @_locked
    def set_stale(self, trace_id: str, node_ids: set[str]) -> None:
        with self._conn:
            self._conn.executemany(
                "UPDATE nodes SET stale = 1 WHERE trace_id = ? AND id = ?",
                [(trace_id, i) for i in node_ids],
            )

    @_locked
    def add_event(self, event: Event) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (trace_id, event) VALUES (?, ?)",
                (event.trace_id, event.model_dump_json()),
            )
        return int(cur.lastrowid or 0)

    @_locked
    def events_after(self, trace_id: str, after_id: int) -> list[tuple[int, Event]]:
        rows = self._conn.execute(
            "SELECT id, event FROM events WHERE trace_id = ? AND id > ? ORDER BY id",
            (trace_id, after_id),
        )
        return [(r[0], Event.model_validate_json(r[1])) for r in rows]

    @_locked
    def mark_running_partial(self) -> int:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE traces SET status = 'partial' WHERE status = 'running'"
            )
        return cur.rowcount
