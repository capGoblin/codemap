"""SQLite connection and migrations. Use one connection per thread."""

import sqlite3
import threading
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1
_MIGRATIONS = "codemap.store.migrations"


class _Connection(sqlite3.Connection):
    """A connection that carries the lock its users share."""

    lock: threading.RLock


def conn_lock(conn: sqlite3.Connection) -> threading.RLock:
    """One lock per connection. Caches and the trace store share it, so threads take turns."""
    if not isinstance(conn, _Connection):
        raise TypeError("connection was not made by open_db")
    return conn.lock


class SchemaTooNewError(Exception):
    """The database was made by a newer codemap."""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, factory=_Connection)
    conn.lock = threading.RLock()
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def _pending(current: int) -> list[tuple[int, str]]:
    found = []
    for item in resources.files(_MIGRATIONS).iterdir():
        if item.name.endswith(".sql"):
            number = int(item.name.split("_", 1)[0])
            if number > current:
                found.append((number, item.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> None:
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise SchemaTooNewError(
            f"database schema {current} is newer than supported {SCHEMA_VERSION}"
        )
    for number, sql in _pending(current):
        # executescript commits first, so the transaction is explicit in the script.
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={number};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
