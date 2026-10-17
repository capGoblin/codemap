"""Test doubles for the model layer."""

from typing import Any

from codemap.agents.model import ModelResponse


class ScriptedModel:
    """Return canned responses in order and keep every request."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> ModelResponse:
        self.requests.append(
            {"system": system, "messages": messages, "tools": tools, "max_tokens": max_tokens}
        )
        return self._responses.pop(0)


def tool_use(name: str, input: dict[str, Any], id: str) -> dict[str, Any]:  # noqa: A002
    return {"type": "tool_use", "id": id, "name": name, "input": input}


def text(s: str) -> dict[str, Any]:
    return {"type": "text", "text": s}


def resp(*blocks: dict[str, Any], stop: str = "tool_use") -> ModelResponse:
    return ModelResponse(content=list(blocks), stop_reason=stop, input_tokens=10, output_tokens=5)
