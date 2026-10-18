"""Chat model protocol and shared types. Provider clients live in `providers`."""

from dataclasses import dataclass
from typing import Any, Protocol


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
