from typing import Any

import pytest
from pydantic import BaseModel

from codemap.agents.limits import Budget, LimitReached, Limits
from codemap.agents.loop import Tool, run_tool_loop
from fakes import ScriptedModel, resp, text, tool_use


class Answer(BaseModel):
    answer: str


def _budget() -> Budget:
    return Budget(Limits(60, 1_000_000, 10.0, 100), price_in=0, price_out=0)


def _run(model: ScriptedModel, tools: list[Tool], **kw: Any) -> Answer:
    return run_tool_loop(
        model, system="s", user="u", tools=tools, submit_schema=Answer, budget=_budget(), **kw
    )


def _echo(calls: list[dict[str, Any]], fail: bool = False) -> Tool:
    def handler(args: dict[str, Any]) -> str:
        calls.append(args)
        if fail:
            raise ValueError("boom")
        return "echoed"

    return Tool("echo", "echo", {"type": "object"}, handler)


def _results(request: dict[str, Any]) -> list[dict[str, Any]]:
    return request["messages"][-1]["content"]


def test_loop_runs_tool_then_submits() -> None:
    calls: list[dict[str, Any]] = []
    model = ScriptedModel(
        [
            resp(tool_use("echo", {"a": 1}, "t1")),
            resp(tool_use("submit", {"answer": "ok"}, "t2")),
        ]
    )
    out = _run(model, [_echo(calls)])
    assert out.answer == "ok"
    assert calls == [{"a": 1}]
    assert {t["name"] for t in model.requests[0]["tools"]} == {"echo", "submit"}


def test_loop_retries_invalid_submit() -> None:
    model = ScriptedModel(
        [
            resp(tool_use("submit", {}, "t1")),
            resp(tool_use("submit", {"answer": "ok"}, "t2")),
        ]
    )
    assert _run(model, []).answer == "ok"
    block = _results(model.requests[1])[0]
    assert block["type"] == "tool_result" and block["tool_use_id"] == "t1"
    assert block["is_error"] is True
    assert "validation" in block["content"]


def test_loop_handler_exception_becomes_error_text() -> None:
    model = ScriptedModel(
        [resp(tool_use("echo", {}, "t1")), resp(tool_use("submit", {"answer": "x"}, "t2"))]
    )
    _run(model, [_echo([], fail=True)])
    block = _results(model.requests[1])[0]
    assert block["content"].startswith("error: ") and "boom" in block["content"]
    assert block["is_error"] is True


def test_loop_nudges_on_text_only() -> None:
    model = ScriptedModel(
        [resp(text("hmm"), stop="end_turn"), resp(tool_use("submit", {"answer": "x"}, "t1"))]
    )
    _run(model, [])
    last = model.requests[1]["messages"][-1]
    assert last["role"] == "user"
    assert last["content"] == "Call a tool, or call submit with your answer."


def test_loop_parallel_tool_calls_all_answered() -> None:
    calls: list[dict[str, Any]] = []
    thinking = {"type": "thinking", "thinking": "hm", "signature": "sig"}
    model = ScriptedModel(
        [
            resp(
                thinking,
                tool_use("echo", {"n": 1}, "a"),
                tool_use("submit", {"answer": "early"}, "b"),
                tool_use("echo", {"n": 2}, "c"),
            ),
        ]
    )
    out = _run(model, [_echo(calls)])
    assert out.answer == "early"
    assert calls == [{"n": 1}, {"n": 2}]

    model = ScriptedModel(
        [
            resp(thinking, tool_use("echo", {"n": 1}, "a"), tool_use("echo", {"n": 2}, "c")),
            resp(tool_use("submit", {"answer": "x"}, "d")),
        ]
    )
    _run(model, [_echo([])])
    msgs = model.requests[1]["messages"]
    assert msgs[1] == {
        "role": "assistant",
        "content": [thinking, tool_use("echo", {"n": 1}, "a"), tool_use("echo", {"n": 2}, "c")],
    }
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["a", "c"]


def test_loop_unknown_tool_is_error() -> None:
    model = ScriptedModel(
        [resp(tool_use("nope", {}, "t1")), resp(tool_use("submit", {"answer": "x"}, "t2"))]
    )
    _run(model, [])
    assert _results(model.requests[1])[0]["is_error"] is True


def test_loop_max_turns() -> None:
    model = ScriptedModel([resp(text("a"), stop="end_turn")] * 3)
    with pytest.raises(LimitReached) as exc:
        _run(model, [], max_turns=2)
    assert exc.value.reason == "max_turns"


def test_loop_trims_old_tool_results() -> None:
    model = ScriptedModel(
        [resp(tool_use("echo", {"n": i}, f"t{i}")) for i in range(3)]
        + [resp(tool_use("submit", {"answer": "x"}, "s"))]
    )
    _run(model, [_echo([])], keep_recent_turns=2)
    last = model.requests[3]["messages"]
    assert last[0] == {"role": "user", "content": "u"}
    assert last[2]["content"][0]["content"] == "[older tool output trimmed]"
    assert last[4]["content"][0]["content"] == "echoed"
    assert last[6]["content"][0]["content"] == "echoed"
    assert last[1]["content"][0]["type"] == "tool_use"
    assert model.requests[1]["messages"][2]["content"][0]["content"] == "echoed"
