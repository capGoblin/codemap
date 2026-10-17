from pathlib import Path

import pytest

from codemap.agents.model import ModelError
from codemap.agents.recording import CachedModel, JsonFileCache, ReplayOnlyModel, request_key
from fakes import ScriptedModel, resp, text

CALL = {
    "system": "s",
    "messages": [{"role": "user", "content": "hi"}],
    "tools": [],
    "max_tokens": 9,
}


def test_cached_model_hits(tmp_path: Path) -> None:
    inner = ScriptedModel([resp(text("a"), stop="end_turn")])
    model = CachedModel(inner, JsonFileCache(tmp_path / "rec.json"))
    first = model.respond(**CALL)
    second = model.respond(**CALL)
    assert first == second
    assert len(inner.requests) == 1


def test_cache_persists_to_file(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    inner = ScriptedModel([resp(text("a"), stop="end_turn")])
    CachedModel(inner, JsonFileCache(path)).respond(**CALL)
    replay = ReplayOnlyModel(JsonFileCache(path))
    assert replay.respond(**CALL).content == [text("a")]


def test_replay_only_miss_raises(tmp_path: Path) -> None:
    replay = ReplayOnlyModel(JsonFileCache(tmp_path / "none.json"))
    with pytest.raises(ModelError, match="no recording"):
        replay.respond(**CALL)


def test_request_key_is_stable_and_sensitive() -> None:
    assert request_key("s", [], [], 1) == request_key("s", [], [], 1)
    assert request_key("s", [], [], 1) != request_key("s", [], [], 2)
