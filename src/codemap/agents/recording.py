"""Record and replay model calls, keyed by a hash of the request."""

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from codemap.agents.model import ChatModel, ModelError, ModelResponse


def request_key(
    model_id: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    """Hash of the request. `model_id` (provider and model) keeps models from sharing replays."""
    payload = {
        "model": model_id,
        "system": system,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class CallCache(Protocol):
    def get(self, key: str) -> ModelResponse | None: ...

    def put(self, key: str, resp: ModelResponse) -> None: ...


class JsonFileCache:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )

    def get(self, key: str) -> ModelResponse | None:
        raw = self._data.get(key)
        return ModelResponse(**raw) if raw else None

    def put(self, key: str, resp: ModelResponse) -> None:
        self._data[key] = {
            "content": resp.content,
            "stop_reason": resp.stop_reason,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=1, sort_keys=True))


class CachedModel:
    def __init__(self, inner: ChatModel, cache: CallCache, model_id: str) -> None:
        self._inner = inner
        self._cache = cache
        self._model_id = model_id

    def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        key = request_key(self._model_id, system, messages, tools, max_tokens)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        resp = self._inner.respond(
            system=system, messages=messages, tools=tools, max_tokens=max_tokens
        )
        if resp.content:  # an empty reply is a failed call; a retry must reach the model
            self._cache.put(key, resp)
        return resp


class ReplayOnlyModel:
    def __init__(self, cache: CallCache, model_id: str) -> None:
        self._cache = cache
        self._model_id = model_id

    def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        hit = self._cache.get(request_key(self._model_id, system, messages, tools, max_tokens))
        if hit is None:
            raise ModelError("no recording")
        return hit
