# 02 — One trace, end to end

`codemap --repo <repo> trace "<question>"`. Each row: what happens · where · DB tables/fields written.

## Phase 1 — Start (CLI → service)

| # | Step | Code | Writes |
| --- | --- | --- | --- |
| 1 | Parse args, load settings (env > `~/.config/codemap/config.toml` > defaults), set up log file | `cli/main.py`, `settings.py`, `logs.py` | `<repo>/.codemap/logs/codemap.log` |
| 2 | Build `Service`: open DB (migrate), mark old `running` traces `partial`, add `.codemap/` to `.git/info/exclude` | `service.py` | `traces.status` |
| 3 | Resolve the question to ≤ 5 entry candidates (agent loop with read tools; or direct `path:Symbol` via index, no model) | `pipeline/resolve.py`, `prompts/resolve.md` | `model_calls` (cache) |
| 4 | Show candidates table, user picks one (`--pick N` skips) | `cli/trace.py`, `cli/render.py` | — |
| 5 | Create trace row (status `running`, commit sha, dirty flag), start background thread | `Service.start_trace` | `traces` (all fields) |

## Phase 2 — Build the graph (background thread, `pipeline/run.py:run_trace`)

| # | Step | Code | Writes |
| --- | --- | --- | --- |
| 6 | **Skeleton walk**: agent walks entry → end at stage level, follows handoffs (webhooks, outbox, workflows), steps over plumbing. Each hop: direct → code check; indirect → verifier agent | `walk.py:walk_skeleton`, `verify.py`, `prompts/walk_skeleton.md`, `verify.md` | `hops.hop` (each as recorded), `walk_effects.effect`, `verdicts`, `events` |
| 7 | **Order points**: DFS from entry; disconnected islands appended in recorded order and joined by async **bridge** hops | `domain/rules.py:ordered_points` | `hops` (bridge, verdict `unsure`), `events` (warning) |
| 8 | **Split phases**: model cuts points into 1–7 stages (titles ≤ 4 words, summary ≤ 14); plumbing folds in | `split.py:split_phases`, `prompts/split_phases.md` | `nodes` (level 0), `edges` |
| 9 | **Deepen each phase**: static call expansion (tree-sitter call sites → in-repo definitions, BFS depth 5, ≤ 80 points); LLM `walk_deepen` only if < 3 points found | `expand.py:expand_static`, `repo/calls.py`, `walk.py:walk_deepen` | `hops` (code_checked) |
| 10 | **Effects per phase**: one model call over the phase's expanded code → R/W effects with real targets; code checks each line | `effects.py:phase_effects`, `prompts/phase_effects.md` | `walk_effects` |
| 11 | **Split children** (levels 1, 2): orchestrator functions collapsed into their callees, `[module]` hints, model groups the rest into children; parallel threads | `split.py:split_children`, `prompts/split_steps.md`, `run.py:_split_level` | `nodes` (level 1–2), `edges` |
| 12 | **Side nodes**: error/branch hops one node deep, dimmed | `split.py:side_nodes` | — |
| 13 | **Validate**: every anchor re-checked; nodes off the path dropped (with reasons); effect rollup from leaves up | `validate.py`, `domain/rules.py` | — |
| 14 | **Save** graph, totals (tokens, cost over both budgets), status + reason | `run.py` | `nodes`, `edges` (replace), `traces.input_tokens/output_tokens/cost_usd/status`, `events` (`finished`) |

Status: `complete`; `partial` when a limit/cancel/drop-ratio > 30% hit; `failed` when no phase survives.

## Phase 3 — View (CLI → server → browser)

| # | Step | Code |
| --- | --- | --- |
| 15 | CLI follows `events` every 0.25 s, shows latest message, hop count, time; prints summary + reason | `cli/trace.py`, `cli/render.py` |
| 16 | Start uvicorn on free `127.0.0.1` port, open browser at `/traces/<id>` | `server/run.py`, `cli/trace.py` |
| 17 | UI loads the full graph, listens to SSE, renders canvas | `frontend/src/App.tsx` |
| 18 | Click node → open in place (camera zooms). No children → `POST expand` builds them | `state/expand.ts` → `run.py:expand_node` |
| 19 | Details tab → `GET detail` → explain made on first open (one model call), stored | `pipeline/explain.py` → `node_details` |

## Ctrl-C / crash

`Service.cancel` sets a cancel event → every agent loop stops before its next model call → status `partial`, everything recorded so far stays (hops, phases saved early).
