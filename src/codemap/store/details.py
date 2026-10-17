"""Stored node explanations. TraceStore calls these under its lock."""

import sqlite3
from datetime import UTC, datetime

from codemap.domain.models import NodeExplain


def load_explain(conn: sqlite3.Connection, trace_id: str, node_id: str) -> NodeExplain | None:
    row = conn.execute(
        "SELECT explain FROM node_details WHERE trace_id = ? AND node_id = ?",
        (trace_id, node_id),
    ).fetchone()
    return NodeExplain.model_validate_json(row[0]) if row else None


def store_explain(
    conn: sqlite3.Connection, trace_id: str, node_id: str, explain: NodeExplain
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO node_details (trace_id, node_id, explain, created_at)"
            " VALUES (?, ?, ?, ?)",
            (trace_id, node_id, explain.model_dump_json(), datetime.now(UTC).isoformat()),
        )
