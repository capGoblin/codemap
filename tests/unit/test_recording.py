from pathlib import Path

import pytest

from codemap.agents.model import ModelError
from codemap.agents.recording import CachedModel, JsonFileCache, ReplayOnlyModel, request_key
from fakes import ScriptedModel, resp, text

MODEL = "openai/gpt-5-nano"
CALL = {
    "system": "s",
    "messages": [{"role": "user", "content": "hi"}],
    "tools": [],
    "max_tokens": 9,
}


def test_cached_model_hits(tmp_path: Path) -> None:
    inner = ScriptedModel([resp(text("a"), stop="end_turn")])
    model = CachedModel(inner, JsonFileCache(tmp_path / "rec.json"), MODEL)
    first = model.respond(**CALL)
    second = model.respond(**CALL)
    assert first == second
    assert len(inner.requests) == 1


def test_empty_reply_is_not_cached(tmp_path: Path) -> None:
    inner = ScriptedModel([resp(stop="max_tokens"), resp(text("a"), stop="end_turn")])
    model = CachedModel(inner, JsonFileCache(tmp_path / "rec.json"), MODEL)
    model.respond(**CALL)
    assert model.respond(**CALL).content == [text("a")]
    assert len(inner.requests) == 2


def test_cache_persists_to_file(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    inner = ScriptedModel([resp(text("a"), stop="end_turn")])
    CachedModel(inner, JsonFileCache(path), MODEL).respond(**CALL)
    replay = ReplayOnlyModel(JsonFileCache(path), MODEL)
    assert replay.respond(**CALL).content == [text("a")]


def test_replay_only_miss_raises(tmp_path: Path) -> None:
    replay = ReplayOnlyModel(JsonFileCache(tmp_path / "none.json"), MODEL)
    with pytest.raises(ModelError, match="no recording"):
        replay.respond(**CALL)


def test_request_key_is_stable_and_sensitive() -> None:
    assert request_key(MODEL, "s", [], [], 1) == request_key(MODEL, "s", [], [], 1)
    assert request_key(MODEL, "s", [], [], 1) != request_key(MODEL, "s", [], [], 2)


def test_request_key_differs_by_model() -> None:
    assert request_key("openai/gpt-5-nano", "s", [], [], 1) != request_key(
        "openai/gpt-5-mini", "s", [], [], 1
    )
    assert request_key("openai/m", "s", [], [], 1) != request_key("anthropic/m", "s", [], [], 1)


def test_replay_does_not_cross_models(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    inner = ScriptedModel([resp(text("a"), stop="end_turn")])
    CachedModel(inner, JsonFileCache(path), MODEL).respond(**CALL)
    with pytest.raises(ModelError, match="no recording"):
        ReplayOnlyModel(JsonFileCache(path), "anthropic/claude-haiku-5-5").respond(**CALL)
