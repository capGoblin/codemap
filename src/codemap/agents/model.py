"""Chat model protocol and the Anthropic-SDK client (MiniMax M3 endpoint)."""

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic


@dataclass(frozen=True)
class ModelResponse:
    content: list[dict[str, Any]]
    stop_reason: str
    input_tokens: int
    output_tokens: int


class ModelError(Exception):
    """The model call failed."""


class ChatModel(Protocol):
    def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse: ...


class AnthropicModel:
    def __init__(self, base_url: str, auth_token: str, model: str, timeout: float) -> None:
        self._model = model
        self._client = anthropic.Anthropic(
            base_url=base_url, auth_token=auth_token, timeout=timeout, max_retries=3
        )

    def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
        try:
            msg = self._client.messages.create(
                model=self._model,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                **kwargs,
            )
        except anthropic.AnthropicError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        return ModelResponse(
            content=[_block(b.model_dump()) for b in msg.content or []],
            stop_reason=msg.stop_reason or "end_turn",
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )


def _block(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields we send back to the API."""
    if raw["type"] == "tool_use":
        return {"type": "tool_use", "id": raw["id"], "name": raw["name"], "input": raw["input"]}
    if raw["type"] == "text":
        return {"type": "text", "text": raw["text"]}
    return raw
