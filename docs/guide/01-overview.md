# 01 — Overview

## What it is

A local CLI. You name a system ("the trace pipeline") or an entry point. codemap traces the real code path with an LLM agent (the configured model), cuts it into nested nodes (phases → steps → sub-steps), records side effects (DB, S3, queues…), stores it in SQLite inside the target repo, and shows it in a browser canvas.

Only the model call leaves the machine. Server binds `127.0.0.1`.

## Layers (enforced by import-linter, `.importlinter`)

```text
cli ──► server ──► service ──► pipeline ──► store / repo / agents ──► domain
```

| Layer | Folder | Job |
| --- | --- | --- |
| cli | `src/codemap/cli/` | Typer commands: `trace`, `open`, `doctor`, hidden `serve-dev`. Prints, prompts, follows progress. No logic. |
| server | `src/codemap/server/` | FastAPI `/api/v1`, SSE events, serves built UI. Thin. |
| service | `src/codemap/service.py` | The ONE app API. CLI and server call only this. Owns threads per trace, git info, staleness. |
| pipeline | `src/codemap/pipeline/` | The trace steps: resolve, walk, verify, expand, effects, split, validate, explain, run. |
| store | `src/codemap/store/` | SQLite: schema, migrations, queries, caches. Per-connection lock. |
| repo | `src/codemap/repo/` | Read-only access to the target repo: sandbox, ignore/secret rules, tools, tree-sitter index, call sites, anchors. |
| agents | `src/codemap/agents/` | Generic LLM machinery: model client, tool loop, budgets, record/replay. Knows nothing about codemap. |
| domain | `src/codemap/domain/` | Pure models (Anchor, Hop, Node, Effect…) and pure rules (path order, rollups, normalisation). |

Other folders:

| Folder | Job |
| --- | --- |
| `src/codemap/prompts/` | One `.md` per agent prompt |
| `frontend/` | Vite + React + TS UI (React Flow + ELK). Built into `src/codemap/server/static/` |
| `evals/` | Golden self-trace of codemap, scorer, verifier hop set, smoke runs |
| `tests/` | pytest: `unit/`, `pipeline/`, `server/`, fixture repo `tests/fixtures/sample_repo/` |
| `scripts/` | Model probe, OpenAPI dump, tree-sitter crash check |
| `docs/` | Specs, plans, this guide, notes (model probe, eval results) |

## Core ideas

- **Anchor** = `file:start-end symbol` (+ content hash). Every node and effect points to real lines. Code checks them.
- **Hop** = "A leads to B" from the walk. Direct hops are checked by code; indirect hops (string dispatch, registries, handoffs) by an independent verifier agent. Recall first: only an evidenced rejection drops a hop.
- **Node** = a unit of work at some level: `title` (≤ 4 words), `summary` (≤ 14 words), anchors, effects, children.
- **Effect** = `category` (db, object_store, queue, cache, file, workflow, http, other) + real `target` name + `op` (read / write only).
- **Phases** are the system's real stages (3–6). Plumbing folds in. Orchestrators become edges.

## Where the main logic is

| Concern | File |
| --- | --- |
| Whole run order | `pipeline/run.py` (`run_trace`, `expand_node`) |
| Stage-level agent walk | `pipeline/walk.py` (`walk_skeleton`, fallback `walk_deepen`) |
| Going deep without the LLM | `pipeline/expand.py` (`expand_static`) + `repo/calls.py` |
| Phases / children | `pipeline/split.py` (`split_phases`, `split_children`), `pipeline/orchestrators.py` (orchestrator collapse) |
| Effects inside phases | `pipeline/effects.py` (`phase_effects`) |
| Checks + rollups | `pipeline/validate.py`, `domain/rules.py` |
| Node details | `pipeline/explain.py` |
| UI graph + layout | `frontend/src/graph/visible.ts`, `layout.ts`, `measure.ts` |
