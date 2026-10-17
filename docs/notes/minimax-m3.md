# MiniMax M3 probe

Probed 2026-10-17 with `scripts/probe_model.py` against `https://api.minimax.io/anthropic`.

- Exact model id: `MiniMax-M3`. The id `MiniMax-M3[1m]` (from the Claude Code env) also works. `DEFAULT_MODEL = "MiniMax-M3"`.
- Tool use works: yes. A single-tool request returned `stop_reason=tool_use`.
- Parallel tool calls: yes. One response held 3 `tool_use` blocks (add, get_weather x2).
- Usage fields present: yes (`input_tokens`, `output_tokens`).
- Price per MTok, up to 512K input: in 0.30 USD, out 1.20 USD. This is the list price (0.60 / 2.40) with the 50% permanent discount shown on https://platform.minimax.io/docs/guides/pricing-paygo.
- Above 512K input tokens the price is about double. Cache reads are 0.06 USD. The code does not model these.
- Source of price: web search of the pricing page, not a live check. Verify before you trust cost limits. Override with `price_in_per_mtok` / `price_out_per_mtok` in config.
