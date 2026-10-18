# 06 — Runtime, safety, ops

## Model

Anthropic SDK pointed at MiniMax (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`), model `MiniMax-M3` (`CODEMAP_MODEL` overrides). `agents/model.py`. Every call goes through `CachedModel` → `model_calls` table: same request = free replay. Probe notes: `docs/notes/minimax-m3.md`.

## Budgets — `agents/limits.py`, `settings.py`

Two budgets so a long walk can never starve the build steps:

| Budget | Used by | Limits (defaults) |
| --- | --- | --- |
| `walk_budget` | resolve, skeleton walk, deepen fallback, verifier | `max_wall_seconds` 900, `max_tokens_total` 2M, `max_cost_usd` 5, `max_tool_calls` 400 |
| `build_budget` | split phases/children, phase effects, explain | `build_max_tokens` 1.5M, `build_max_tool_calls` 300 (shares wall clock) |

Other knobs: `max_hops` 200, `skeleton_hops` 40, `deepen_hops` 160, `deepen_max_depth` 5, `deepen_max_points` 80, `split_concurrency` 4. A hit limit → `LimitReached` → that step stops, trace ends `partial` with the reason. Long agent loops trim old tool output (keep last 12 turns).

## Threads

- One background thread per trace (`Service.start_trace`), own context + DB connection.
- Child splits run on a small pool; workers only call the model; all store writes and events happen on the trace thread.
- One `RLock` per SQLite connection; caches and `TraceStore` hold it.
- Cancel: `Service.cancel` → cancel event → checked before every model call → `partial`.

## Safety — `repo/`

| Rule | Where |
| --- | --- |
| Paths resolve inside repo root; no `..`, absolute paths, symlink escapes | `repo/sandbox.py` |
| Canonical on-disk spelling before checks (macOS case tricks blocked) | `repo/tools.py:_resolve_visible` |
| Ignored: `.git`, deps, build, lockfiles, binaries, all git ignores (nested, `info/exclude`, global) | `repo/ignore.py` |
| Secret deny list even if not git-ignored: `.env*`, keys, `.npmrc`, `.netrc`, `credentials*`, `.aws/`, `.ssh/`, `*.tfvars`, `.git-credentials`… | `repo/ignore.py` |
| Model-supplied search globs can never widen visibility; results re-filtered | `repo/tools.py:search` |
| No shell tool; agent tools are read-only | `pipeline/context.py:read_tools` |
| Token never logged or stored | `logs.py` redaction filter |

## Grammar / index

tree-sitter (`tree-sitter` 0.25.x, `tree-sitter-language-pack` 0.13.x — bundled grammars, offline; 0.26 crashes). Outline cached per file hash in `symbols`. No grammar → regex fallback. Check: `uv run python scripts/check_index.py <repo>`.

## CLI

| Command | Does |
| --- | --- |
| `codemap trace "<q>" [--pick N] [--lazy] [--json] [--no-open]` | resolve → pick → trace → open browser (Ctrl-C = partial) |
| `codemap open [TRACE_ID]` | list / serve a saved trace |
| `codemap doctor` | env, model reachable, ripgrep, DB schema, Python |
| `codemap serve-dev [--port] [--static]` | hidden; API for frontend dev |

Global: `--repo PATH`, `--verbose`, `--version`.

## Evals — `evals/`

| File | Does |
| --- | --- |
| `example-file-parsing.expected.json` | golden example trace: Upload / Parse / Interpret (Locate, Extract, Map, Gate…) / Load, with spans + effects |
| `score.py` | off-path nodes, phase/step agreement (any depth), depth recall, effect recall, title/summary/phase-count checks |
| `run_golden.py` | run + score example (`--record` = real model, else replay) |
| `hops/hops.json`, `run_verifier.py` | 30 real + 21 fake indirect hops; real-rejected rate bar 2% |
| `smoke.json`, `run_smoke.py` | one system per repo (chat-agent, pi, qm, agent-cli, example); status/cost/time table → `docs/notes/eval-results.md` |

## Quality gate

`make check` = ruff, ruff format, mypy strict, import-linter, pytest, frontend typecheck + vitest. Playwright: `npx --prefix frontend playwright test` (mocked smoke + real-server spec).
