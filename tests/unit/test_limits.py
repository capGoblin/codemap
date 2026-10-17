import pytest

from codemap.agents.limits import Budget, LimitReached, Limits
from codemap.agents.model import ModelResponse
from fakes import resp, text

LIMITS = Limits(wall_seconds=10, max_tokens=10_000_000, max_cost_usd=1.0, max_tool_calls=3)


def test_budget_cost_limit() -> None:
    budget = Budget(LIMITS, price_in=1.0, price_out=1.0)
    budget.charge(ModelResponse([], "end_turn", 2_000_000, 0))
    with pytest.raises(LimitReached) as exc:
        budget.check()
    assert "cost" in exc.value.reason


def test_budget_wall_limit() -> None:
    now = [0.0]
    budget = Budget(LIMITS, price_in=0, price_out=0, clock=lambda: now[0])
    budget.check()
    now[0] = 11.0
    with pytest.raises(LimitReached) as exc:
        budget.check()
    assert "wall" in exc.value.reason


def test_budget_token_limit() -> None:
    limits = Limits(wall_seconds=10, max_tokens=16, max_cost_usd=1.0, max_tool_calls=3)
    budget = Budget(limits, price_in=0, price_out=0)
    budget.charge(resp(text("x")))
    budget.check()
    budget.charge(resp(text("x")))
    assert budget.input_tokens == 20 and budget.output_tokens == 10
    with pytest.raises(LimitReached) as exc:
        budget.check()
    assert "tokens" in exc.value.reason


def test_budget_tool_call_limit() -> None:
    budget = Budget(LIMITS, price_in=0, price_out=0)
    for _ in range(3):
        budget.check()
        budget.count_tool_call()
    with pytest.raises(LimitReached) as exc:
        budget.check()
    assert "tool" in exc.value.reason
