"""SQLite-backed caches for model calls, symbol outlines and verifier verdicts."""

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from codemap.agents.model import ModelResponse
from codemap.domain.models import Anchor, VerifierResult
from codemap.repo.index import Symbol
from codemap.store.db import conn_lock


class SqliteCallCache:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = conn_lock(conn)

    def get(self, key: str) -> ModelResponse | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM model_calls WHERE key = ?", (key,)
            ).fetchone()
        return ModelResponse(**json.loads(row[0])) if row else None

    def put(self, key: str, resp: ModelResponse) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO model_calls (key, response) VALUES (?, ?)",
                (key, json.dumps(asdict(resp))),
            )


class SqliteSymbolCache:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = conn_lock(conn)

    def get(self, content_hash: str) -> list[Symbol] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT symbols FROM symbols WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        if row is None:
            return None
        items: list[dict[str, Any]] = json.loads(row[0])
        return [Symbol(**item) for item in items]

    def put(self, content_hash: str, symbols: list[Symbol]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO symbols (content_hash, symbols) VALUES (?, ?)",
                (content_hash, json.dumps([asdict(s) for s in symbols])),
            )


class SqliteVerdictCache:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = conn_lock(conn)

    def get(self, key: str) -> VerifierResult | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT verdict, evidence, suggested FROM verdicts WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        suggested = Anchor.model_validate_json(row[2]) if row[2] else None
        return VerifierResult.model_validate(
            {"verdict": row[0], "evidence": row[1], "suggested_callee": suggested}
        )

    def put(self, key: str, result: VerifierResult) -> None:
        suggested = result.suggested_callee
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO verdicts (key, verdict, evidence, suggested)"
                " VALUES (?, ?, ?, ?)",
                (
                    key,
                    result.verdict,
                    result.evidence,
                    suggested.model_dump_json() if suggested else None,
                ),
            )
