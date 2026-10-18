# codemap v2 — Guide

Short, high-level map of the codebase. Read in order.

| Doc | What it covers |
| --- | --- |
| [01-overview.md](01-overview.md) | What codemap is, the layers, where each thing lives |
| [02-trace-flow.md](02-trace-flow.md) | One `codemap trace` end to end, step by step (like a trace summary) |
| [03-pipeline.md](03-pipeline.md) | Each pipeline stage: inputs, outputs, model calls, rules |
| [04-data.md](04-data.md) | Domain models and every SQLite table + field, who reads/writes it |
| [05-server-ui.md](05-server-ui.md) | HTTP API, live events, frontend architecture, UI flows |
| [06-runtime-ops.md](06-runtime-ops.md) | Budgets, threads, cancel, caches, sandbox, config, CLI, evals, dev loop |

Specs and plans (the "why"): `docs/specs/`, `docs/plans/`.
