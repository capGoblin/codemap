import json
from types import SimpleNamespace
from typing import Any

import openai
import pytest

from codemap.agents.model import ModelError
from codemap.agents.providers import AnthropicModel, OpenAIModel, make_model, to_openai_messages
from codemap.settings import Settings

TOOL = {
    "name": "grep",
    "description": "Search.",
    "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
}


def test_three_turn_conversation_translates() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "find it"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking."},
                {"type": "tool_use", "id": "t1", "name": "grep", "input": {"q": "x"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "a.py:1"},
                {"type": "text", "text": "continue"},
            ],
        },
    ]
    assert to_openai_messages("sys", messages) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "find it"},
        {
            "role": "assistant",
            "content": "Looking.",
            "tool_calls": [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "grep", "arguments": json.dumps({"q": "x"})},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "a.py:1"},
        {"role": "user", "content": "continue"},
    ]


def test_assistant_tool_only_has_no_content() -> None:
    blocks = [{"type": "tool_use", "id": "t1", "name": "grep", "input": {}}]
    out = to_openai_messages("s", [{"role": "assistant", "content": blocks}])
    assert out[1]["content"] is None


class FakeCompletions:
    def __init__(self, completion: Any) -> None:
        self._completion = completion
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self._completion, Exception):
            raise self._completion
        return self._completion


def openai_model(completion: Any) -> tuple[OpenAIModel, FakeCompletions]:
    model = OpenAIModel("key", "gpt-5-nano", 5)
    fake = FakeCompletions(completion)
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))  # type: ignore[assignment]
    return model, fake


def completion(
    content: str | None, calls: list[Any] | None, finish: str, usage: tuple[int, int] = (7, 3)
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]),
    )


def call(id: str, name: str, arguments: str) -> Any:  # noqa: A002
    return SimpleNamespace(
        id=id, type="function", function=SimpleNamespace(name=name, arguments=arguments)
    )


def respond(model: OpenAIModel) -> Any:
    return model.respond(
        system="s", messages=[{"role": "user", "content": "q"}], tools=[TOOL], max_tokens=99
    )


def test_openai_tool_calls_become_tool_use() -> None:
    model, fake = openai_model(
        completion("hm", [call("c1", "grep", '{"q": "x"}')], "tool_calls", (11, 4))
    )
    result = respond(model)
    assert result.content == [
        {"type": "text", "text": "hm"},
        {"type": "tool_use", "id": "c1", "name": "grep", "input": {"q": "x"}},
    ]
    assert (result.stop_reason, result.input_tokens, result.output_tokens) == ("tool_use", 11, 4)
    assert fake.kwargs["max_completion_tokens"] == 99
    assert "max_tokens" not in fake.kwargs
    assert "temperature" not in fake.kwargs
    assert fake.kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "grep",
                "description": "Search.",
                "parameters": TOOL["input_schema"],
            },
        }
    ]
    assert fake.kwargs["messages"][0] == {"role": "system", "content": "s"}


def test_openai_bad_arguments_become_empty_input() -> None:
    model, _ = openai_model(completion(None, [call("c1", "grep", "{oops")], "tool_calls"))
    assert respond(model).content == [{"type": "tool_use", "id": "c1", "name": "grep", "input": {}}]


@pytest.mark.parametrize(
    ("finish", "expected"), [("stop", "end_turn"), ("length", "max_tokens"), ("other", "end_turn")]
)
def test_openai_stop_reasons(finish: str, expected: str) -> None:
    model, _ = openai_model(completion("done", None, finish))
    assert respond(model).stop_reason == expected


def test_openai_sdk_error_becomes_model_error() -> None:
    model, _ = openai_model(openai.OpenAIError("bad request"))
    with pytest.raises(ModelError, match="OpenAIError: bad request"):
        respond(model)


def test_make_model_picks_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(make_model(Settings(api_key="k")), OpenAIModel)
    assert isinstance(make_model(Settings(provider="anthropic", api_key="k")), AnthropicModel)


def test_make_model_missing_key_names_the_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ModelError, match="OPENAI_API_KEY"):
        make_model(Settings())
    with pytest.raises(ModelError, match="ANTHROPIC_API_KEY"):
        make_model(Settings(provider="anthropic"))


def test_empty_assistant_turn_sends_empty_string() -> None:
    # a reasoning model can spend its whole output budget and return no text and no tool call
    out = to_openai_messages("s", [{"role": "assistant", "content": []}])
    assert out[1] == {"role": "assistant", "content": ""}
