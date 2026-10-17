"""Generic tool loop: the model calls tools until it calls `submit` with a valid answer."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from codemap.agents.limits import Budget, LimitReached
from codemap.agents.model import ChatModel

SUBMIT = "submit"
NUDGE = "Call a tool, or call submit with your answer."
TRIMMED = "[older tool output trimmed]"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


def run_tool_loop[T: BaseModel](
    model: ChatModel,
    *,
    system: str,
    user: str,
    tools: Sequence[Tool],
    submit_schema: type[T],
    budget: Budget,
    max_turns: int = 60,
    max_tokens: int = 4096,
    keep_recent_turns: int | None = None,
) -> T:
    handlers = {t.name: t.handler for t in tools}
    specs = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
    specs.append(
        {
            "name": SUBMIT,
            "description": "Submit your final answer. Call this once when done.",
            "input_schema": submit_schema.model_json_schema(),
        }
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    for _ in range(max_turns):
        budget.check()
        resp = model.respond(
            system=system,
            messages=_trimmed(messages, keep_recent_turns),
            tools=specs,
            max_tokens=max_tokens,
        )
        budget.charge(resp)
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.get("type") == "tool_use"]
        if not uses:
            messages.append({"role": "user", "content": NUDGE})
            continue
        results: list[dict[str, Any]] = []
        answer: T | None = None
        for block in uses:
            budget.count_tool_call()
            if block["name"] == SUBMIT:
                content, parsed = _submit(submit_schema, block["input"])
                if parsed is not None and answer is None:
                    answer = parsed
                results.append(_result(block, content, parsed is None))
            else:
                results.append(_run_handler(handlers, block))
        if answer is not None:
            return answer
        messages.append({"role": "user", "content": results})
    raise LimitReached("max_turns")


def _trimmed(messages: list[dict[str, Any]], keep: int | None) -> list[dict[str, Any]]:
    """Copy of `messages` with tool results older than the last `keep` assistant turns stubbed."""
    if keep is None:
        return list(messages)
    turns = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    if len(turns) <= keep:
        return list(messages)
    cutoff = turns[-keep] if keep > 0 else len(messages)
    return [_stub_results(m) if i < cutoff else m for i, m in enumerate(messages)]


def _stub_results(message: dict[str, Any]) -> dict[str, Any]:
    content = message["content"]
    if message["role"] != "user" or not isinstance(content, list):
        return message
    stubbed = [{**b, "content": TRIMMED} if b.get("type") == "tool_result" else b for b in content]
    return {**message, "content": stubbed}


def _submit[T: BaseModel](schema: type[T], raw: dict[str, Any]) -> tuple[str, T | None]:
    try:
        return "accepted", schema.model_validate(raw)
    except ValidationError as exc:
        return f"validation error: {exc}", None


def _run_handler(
    handlers: dict[str, Callable[[dict[str, Any]], str]], block: dict[str, Any]
) -> dict[str, Any]:
    handler = handlers.get(block["name"])
    if handler is None:
        return _result(block, f"error: unknown tool {block['name']}", True)
    try:
        return _result(block, handler(block["input"]), False)
    except Exception as exc:  # noqa: BLE001 - any handler failure goes back to the model
        return _result(block, f"error: {exc}", True)


def _result(block: dict[str, Any], content: str, is_error: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "tool_result", "tool_use_id": block["id"], "content": content}
    if is_error:
        out["is_error"] = True
    return out
