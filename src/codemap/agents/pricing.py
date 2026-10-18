"""Model prices in USD per million tokens (input, output)."""

PRICES: dict[str, tuple[float, float]] = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}


def price_for(
    model: str, override_in: float | None = None, override_out: float | None = None
) -> tuple[float, float] | None:
    """Return (input, output) prices, or None when the model is unknown and not overridden."""
    known = PRICES.get(model)
    if known is None:
        keys = [k for k in PRICES if model.startswith(k)]
        known = PRICES[max(keys, key=len)] if keys else None
    if override_in is not None and override_out is not None:
        return (override_in, override_out)
    if known is None:
        return None
    return (
        known[0] if override_in is None else override_in,
        known[1] if override_out is None else override_out,
    )
