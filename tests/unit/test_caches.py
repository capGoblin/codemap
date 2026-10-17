from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from codemap.agents.model import ModelResponse
from codemap.repo.index import Symbol
from codemap.store.caches import SqliteCallCache, SqliteSymbolCache
from codemap.store.db import open_db


def test_caches_thread_safe(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "db.sqlite")
    calls, symbols = SqliteCallCache(conn), SqliteSymbolCache(conn)

    def work(worker: int) -> None:
        for i in range(200):
            key = f"{worker}-{i}"
            calls.put(
                key,
                ModelResponse(content=[], stop_reason="end_turn", input_tokens=i, output_tokens=1),
            )
            symbols.put(
                key,
                [Symbol(name=key, kind="function", start_line=1, end_line=2, signature="def f()")],
            )
            got = calls.get(key)
            assert got is not None and got.input_tokens == i
            sym = symbols.get(key)
            assert sym is not None and sym[0].name == key

    with ThreadPoolExecutor(8) as pool:
        for f in [pool.submit(work, w) for w in range(8)]:
            f.result()
    assert all(calls.get(f"{w}-{i}") for w in range(8) for i in range(200))
