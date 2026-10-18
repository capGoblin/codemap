import pytest

from codemap.agents.limits import Budget, LimitReached, Limits
from codemap.agents.pricing import price_for
from fakes import resp


def test_exact_match() -> None:
    assert price_for("gpt-5-nano") == (0.05, 0.40)
    assert price_for("gpt-5") == (1.25, 10.00)


def test_longest_prefix_wins() -> None:
    assert price_for("gpt-5-nano-2025-08-07") == (0.05, 0.40)
    assert price_for("gpt-5-mini-x") == (0.25, 2.00)
    assert price_for("gpt-5.1") == (1.25, 10.00)


def test_unknown_is_none_unless_overridden() -> None:
    assert price_for("mystery") is None
    assert price_for("mystery", 1.0, 2.0) == (1.0, 2.0)
    assert price_for("mystery", 1.0, None) is None


def test_partial_override_keeps_known_side() -> None:
    assert price_for("gpt-5-nano", 9.0, None) == (9.0, 0.40)


def test_budget_without_price_skips_cost_limit() -> None:
    budget = Budget(Limits(60, 10_000_000, 0.01, 100), price_in=None, price_out=None)
    budget.charge(resp(stop="end_turn"))
    assert budget.cost_usd == 0.0
    budget.check()


def test_budget_with_price_enforces_cost() -> None:
    budget = Budget(Limits(60, 10_000_000, 0.000001, 100), price_in=1.0, price_out=1.0)
    budget.charge(resp(stop="end_turn"))
    with pytest.raises(LimitReached, match="cost"):
        budget.check()
