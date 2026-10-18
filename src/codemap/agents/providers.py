"""Provider clients behind `ChatModel`. The internal format is the Anthropic Messages format."""

import json
from typing import Any

import anthropic
import openai

from codemap.agents.model import ChatModel, ModelError, ModelResponse
from codemap.settings import FALLBACK_KEY_VARS, Settings

_MAX_RETRIES = 3
_STOP_REASONS = {"tool_calls": "tool_use", "length": "max_tokens"}
# reasoning tokens count against max_completion_tokens; without room the answer comes back empty
REASONING_HEADROOM = 16_000
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class AnthropicModel:
    def __init__(
        self, api_key: str, model: str, timeout: float, base_url: str | None = None
    ) -> None:
        self._model = model
        self._client = anthropic.Anthropic(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=_MAX_RETRIES
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


class OpenAIModel:
    def __init__(
        self, api_key: str, model: str, timeout: float, base_url: str | None = None
    ) -> None:
        self._model = model
        self._client = openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=_MAX_RETRIES
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
            kwargs["tools"] = [_openai_tool(t) for t in tools]
        if self._model.startswith(_REASONING_PREFIXES):
            kwargs["reasoning_effort"] = "low"
            max_tokens += REASONING_HEADROOM
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=to_openai_messages(system, messages),  # type: ignore[arg-type]
                max_completion_tokens=max_tokens,
                **kwargs,
            )
        except openai.OpenAIError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        choice = completion.choices[0]
        message = choice.message
        content: list[dict[str, Any]] = []
        if message.content:
            content.append({"type": "text", "text": message.content})
        for call in message.tool_calls or []:
            if call.type != "function":
                continue
            content.append(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.function.name,
                    "input": _parse_arguments(call.function.arguments),
                }
            )
        usage = completion.usage
        return ModelResponse(
            content=content,
            stop_reason=_STOP_REASONS.get(choice.finish_reason, "end_turn"),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


def _openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Anthropic-format messages into Chat Completions messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": message["role"], "content": content})
        elif message["role"] == "assistant":
            out.append(_assistant(content))
        else:
            out.extend(_user_blocks(content))
    return out


def _assistant(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    text = "".join(b["text"] for b in blocks if b["type"] == "text")
    calls = [
        {
            "id": b["id"],
            "type": "function",
            "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
        }
        for b in blocks
        if b["type"] == "tool_use"
    ]
    # null content is valid only next to tool calls; an empty turn must still send a string
    out: dict[str, Any] = {"role": "assistant", "content": text or (None if calls else "")}
    if calls:
        out["tool_calls"] = calls
    return out


def _user_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tool results come first (they must follow the tool calls), then any plain text."""
    out = [
        {"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]}
        for b in blocks
        if b["type"] == "tool_result"
    ]
    text = "".join(b["text"] for b in blocks if b["type"] == "text")
    if text:
        out.append({"role": "user", "content": text})
    return out


def make_model(settings: Settings) -> ChatModel:
    """Build the client for `settings.provider`. Raises ModelError when no key is set."""
    key = settings.resolved_api_key()
    if not key:
        var = FALLBACK_KEY_VARS[settings.provider]
        raise ModelError(f"no API key: set {var}, or pass --api-key")
    cls = AnthropicModel if settings.provider == "anthropic" else OpenAIModel
    return cls(key, settings.resolved_model, settings.request_timeout_s, settings.base_url)
