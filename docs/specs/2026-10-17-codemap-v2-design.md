# codemap v2 — Design

Date: 2026-10-17. Status: approved.

## 1. Intent

codemap is a local CLI. It shows a human how one system in a codebase works, end to end, as a zoomable graph.

The user names a system ("the file parsing system") or an entry point (an API route). codemap traces the real execution path and shows:

- **Level 0 (HLD):** the phases of the flow.
- **Level 1 (LLD):** the steps inside each phase.
- **Detail:** for a step, the functions, their input and output, and the code.
- **Side effects at every level:** DB reads and writes (tables, fields), S3/object storage, queues, caches, files, workflow handoffs, external calls.

The goal: a human understands the architecture and how data changes through the system, and can later match the graph to the code.

v2 is a full rewrite in a new directory, `codemap-v2/`. The name stays `codemap`. The v1 repo-wide map (one node per file, Louvain clusters) is dropped.

## 2. Goals, non-goals, anti-goals

**Goals**

- Any language, any framework. No per-language logic is required for correctness.
- Production quality: typed, tested, small modules with enforced layers.
- Every node is grounded in code: it has `file:line` anchors that code verifies.
- Works on very large codebases within bounded cost and time. Evals target codemap itself and a small fixture repo. Users add their own repos.
- **Index (my call):** the tree-sitter index is built lazily, per file, when a tool first needs that file. It is cached in SQLite by file content hash. A trace touches a small slice of the repo, so a full up-front index is not needed. A single agent is enough at this scale while subagents are parked.

**Non-goals (this version)**

- Repo-wide map.
- Chat or "ask about this node".
- Subagent delegation (parked, §10).
- Multi-repo flows.
- Hosted service. Only the model call leaves the machine.

**Anti-goals (failure even if it "works")**

1. **Nodes for code that does not run in this flow.** Dead code, unrelated modules, or doc-only concepts appear in the graph.
2. **Vague phase or step splits.** Splits that do not match how the code itself divides the work, or splits that are generic ("process data", "handle logic").

## 3. User flow

```text
$ cd <repo>
$ codemap trace "how a trace is saved"
  → resolving entry points...
  1) src/codemap/pipeline/run.py:run_trace
  2) src/codemap/cli/main.py:trace
  Pick entry point [1]: 2
  → tracing... (streamed step progress)
  → opened http://localhost:<port>/traces/<id>
```

- Input is free text or a direct entry point (`path:symbol`, or route such as `POST /traces`).
- codemap resolves the input to ranked candidate entry points. **The user must confirm one before tracing starts.**
- Default: build all levels at trace time.
- `--lazy`: build Level 0 only. Build deeper levels when the user opens a node.
- `codemap open` lists saved traces for the repo and opens one.

## 4. Data model

### 4.1 Trace

One trace = one confirmed entry point + one question, at one commit.

Fields: id, question, entry point, commit sha, dirty-tree flag, status (`running`, `complete`, `partial`, `failed`), mode (`eager`, `lazy`), created time, model, token and cost totals.

### 4.2 Node

A node is a unit of work that happens **in** the flow. Processing lives in nodes, not edges.

| Field | Meaning |
| --- | --- |
| `level` | 0 = phase, 1 = step |
| `parent_id` | null for phases |
| `order` | position among siblings |
| `title` | short name, from the code's own name where one exists |
| `does` | what happens inside, 1–3 sentences |
| `input` | data shape that comes in (type name + key fields) |
| `output` | data shape that goes out |
| `boundary_reason` | why this node starts/ends here (§5.2) |
| `anchors` | list of `{file, start_line, end_line, symbol, content_hash}` |
| `effects` | list of side effects (§4.4) |
| `stale` | true when an anchor's content hash no longer matches the file |

**Detail (per step):** the functions in the step's anchors. For each: signature, input, output, the code snippet, calls to other functions. The snippet is read from disk through the anchor. It is not stored.

### 4.3 Edge

An edge shows order and handoff only. It carries no transformation.

`kind`: `call` (sync), `async` (queue, job, workflow, event, outbox), `error` (error/retry path), `branch` (alternate path such as a feature flag).

The main path is drawn solid. `error` and `branch` edges and their nodes are drawn dimmed.

### 4.4 Effect

| Field | Meaning |
| --- | --- |
| `category` | `db`, `object_store`, `queue`, `cache`, `file`, `workflow`, `http`, `other` |
| `target` | table / bucket+key pattern / topic / cache key / path / workflow / URL host |
| `fields` | fields or columns touched, when known |
| `op` | `read`, `write`, `delete`, `publish`, `consume`, `call` |
| `anchor` | `file:line` of the code that does it |

A phase's effects are the union of its steps' effects. **Code computes this rollup. The model does not.**

## 5. Rules

### 5.1 Only code that runs

- Every node must have at least one anchor on the traced call path from the confirmed entry point.
- The path is recorded as the agent walks it (each hop: caller anchor → callee anchor).
- A validation pass drops any node whose anchors are not on the recorded path.
- **The trace follows async handoffs across process boundaries.** When the code starts a workflow, enqueues a job, or publishes an event, the tracer resolves it to the handler on the other side and continues. The handoff becomes an `async` edge. Resolving handoffs is core trace-path work. It is not optional.
- **Flow shape (my call):** the main path is one ordered sequence of phases. Inside a phase, steps can fan out in parallel (for example, parallel activities), drawn side by side. `branch` and `error` paths are traced to their first node only and drawn dimmed off the main path. They are not traced further.

### 5.2 Splits follow the code first

Priority for phase and step boundaries:

1. **The code's own structure:** workflow/activity definitions, pipeline stage modules, handler → service → repository layers, named functions.
2. **Agent judgment, only where the code is vague,** in part or in whole. The prompt for this case is tuned separately. Judgment uses these signals: the data shape changes, a commit or write happens, an async handoff happens, a module or service boundary is crossed.

Each node records `boundary_reason`. It is used for eval and debugging. It is not shown in the UI.

### 5.3 Grounding checks (code, not model)

- Every anchor's file exists inside the repo root, the line range is valid, and the symbol appears in that range.
- Every effect has an anchor that passes the same check.
- For a phase: the first step's input matches the phase input, and the last step's output matches the phase output. A mismatch is recorded as a warning on the node.
- A failed check removes the claim. If too many claims fail, the run ends as `partial`.

### 5.4 Hop verification

**Priority: never lose a real hop.** A real hop that is dropped can hide a whole tail of the flow. A small number of wrong hops is accepted as the cost of this.

A **hop** is one "A leads to B" claim the trace agent records. Each hop has a type:

| Hop type | Example | Checked by |
| --- | --- | --- |
| `direct` | `accept_document(file)` inside `upload()` | Code: the callee name appears in the caller's anchored range. |
| `indirect` | string dispatch (`execute_activity("parse_document")`), registry or dict lookup, decorator or route wiring, dependency injection, framework callback, async handoff (§5.1) | **Verifier agent.** |

- A `direct` hop that fails the code check becomes `indirect` and goes to the verifier. It is never dropped by code alone.
- **Verifier agent:** a separate agent with its own fresh context and the same read-only tools. It gets only the claim: caller anchor, callee anchor, hop type, and the wiring line the trace agent cites, if any. It does **not** get the trace agent's reasoning or conversation. This stops it from repeating the trace agent's mistake.
- The verifier searches the code itself and returns one verdict, with the anchors it used:
  - `confirmed`: keep the hop.
  - `unsure`: **keep the hop** (recall first).
  - `rejected`: drop the hop. A rejection must cite evidence, for example "the string `parse_document` is registered to `parse_v2` at `worker.py:40`". The verifier can give the correct callee instead.
- **Timing (my call):** verification is blocking and happens when the hop is recorded. When the trace agent records an `indirect` hop, the `record_hop` tool result returns the verifier's verdict. On `rejected`, the result carries the reason and the suggested callee, so the trace agent continues from the right place and wastes no work on a wrong subtree. Indirect hops are a small share of all hops, so the wait is acceptable.
- Verdicts are cached by hop (caller anchor hash + callee anchor hash). Identical hops are not re-verified.
- Every verdict and its evidence is stored for eval and debugging. The UI shows no verdict marker.

## 6. Pipeline

Fixed steps in code. The model is called only inside bounded steps. Each step has its own prompt, schema and budget.

1. **Resolve.** Agent tool loop: find ranked entry point candidates for the input. Output is schema-validated.
2. **Confirm.** CLI prompt. No model.
3. **Trace path.** Agent tool loop from the entry point. It walks the real call path with cheap tools and records hops and effects. It reads signatures and short ranges, not whole large files where it can avoid it. Indirect hops go to the verifier agent while the trace runs (§5.4).
4. **Split Level 0.** One structured call: split the recorded path into contiguous phase spans (§5.2).
5. **Split Level 1.** For each phase: one structured call (with tool access if needed) to split its span into steps, with input, output, effects. Phases run with bounded concurrency. Skipped in `--lazy` mode until the user opens the phase.
6. **Build detail.** Deterministic: read signatures and snippets from anchors.
7. **Validate.** §5.1 and §5.3. Compute effect rollups.
8. **Store.** Write to SQLite (§8). Emit a final event.

Every step emits progress events (step started, hop found, phase split, warnings, finished).

## 7. Agent runtime

- **Own small tool loop.** No LangChain, LangGraph or deepagents. Use the provider SDK directly (OpenAI or Anthropic), configured by environment variables.
- **Model:** the configured model (default `gpt-5-nano`). The model name is a constant, overridable by env.
- **Tools (read-only, sandboxed to repo root, no shell):** `list_dir`, `read_file(path, start, end)`, `search(pattern, glob)` (ripgrep), `find_definition(symbol)`, `outline(path)` (symbols and signatures in a file), `record_hop`, `record_effect`.
- **Two agents:** the trace agent and the verifier agent (§5.4). Both use the same tool loop and tools. They differ in prompt, context and output schema. The verifier has no `record_*` tools.
- **Symbol index:** tree-sitter (language pack with many grammars) builds `find_definition` and `outline`. It is a speed-up only. If a language has no grammar, these tools fall back to `search`. Truth comes from reading code.
- **Contracts as `Protocol`s** (`Model`, `RepoReader`, `Store`). Code calls the protocol, never the SDK directly.
- **Run context with hard limits:** wall time, tokens, cost, tool calls, hops. A limit hit ends the run as `partial`, with what was found so far kept.
- **Record and replay** of model calls, so tests and evals do not call the real API.
- **Ignore list** before any model sees a path: `.git`, dependency dirs, build output, lockfiles, binaries, and `.gitignore` entries.

## 8. Storage

One SQLite file per repo: `<repo>/.codemap/codemap.db`. codemap adds `.codemap/` to the repo's `.git/info/exclude` on first run, not to `.gitignore`.

**Store:** traces, nodes, edges, effects, anchors with content hashes, recorded path hops with type and verifier verdict and evidence, run events (progress, warnings, tokens, cost), model-call cache keyed by request hash.

**Do not store:** source code copies, file contents, API keys or tokens.

**Staleness:** on open, codemap re-hashes anchored ranges. Changed anchors mark nodes `stale`. Re-trace is a user action.

Schema migrations are versioned from the first release.

## 9. Server and UI

### 9.1 Server

FastAPI, local only, thin. No business logic. It calls into the pipeline and store.

- `GET /api/v1/traces` — list.
- `GET /api/v1/traces/{id}?depth=N` — nodes, edges, effects down to depth N.
- `GET /api/v1/traces/{id}/events` — SSE progress stream.
- `POST /api/v1/traces/{id}/nodes/{node_id}/expand` — lazy mode: build children.
- `GET /api/v1/traces/{id}/nodes/{node_id}/detail` — functions and snippets, read from disk.

### 9.2 UI

Vite + React + TypeScript. `@xyflow/react` for the canvas. `elkjs` for layout. dagre is not used because it breaks on nested groups with outside edges.

Approved behaviour (from mockups):

- **Start:** all phases closed, left to right, connected by typed edges. Each phase shows title, `input → output`, and effect chips (write / read colours).
- **Zoom-in expand:** clicking a phase opens it **in place**. Its steps appear inside it, the rest of the flow moves to make room, and the camera zooms onto the opened phase. Neighbours stay visible at the edges. The user zooms out to see the whole flow. **No breadcrumb, no separate screen.**
- The user can open one node or many. Toolbar: **Expand all**, **Collapse all**, **Fit**.
- Layout: on every open/close, run ELK on the visible graph and animate nodes to new positions.
- **Detail panel:** clicking a step opens a side panel: anchor `file:line`, input, what it does, output, effects, functions with code snippets, calls.
- **Effect lane:** a lane under the flow lists every effect target the trace touches (tables, buckets, queues, caches, files, workflows, external hosts) with fields and ops. Clicking a target highlights the nodes that touch it and fades the rest. The target lists which node reads or writes which field.
- No "from code / inferred" tag in the UI.
- **Effect categories** each have one colour and label, used everywhere: DB, Object store, Queue/Workflow, Cache, File, External call. Ops: `W` write, `R` read, `D` delete, `P` publish/start, `C` call.
- **Effect chips on nodes:** op first, at most 3, then `+N`. Category filters in the toolbar hide or show a category everywhere.
- **Effect lane** is grouped in columns by category.
- **Effect detail panel:** clicking a chip or a lane target lists each op with node and `file:line`. Clicking a line moves the camera to that node.
- No effect matrix view.

## 10. Parked (later versions)

- **Subagent delegation** per phase when a flow is too large for one agent. Needs its own research pass before design.
- Ask about a node in place.
- Re-trace only stale parts.

## 11. Testing and evaluation

- Unit tests for validation, rollup, staleness, store, tools sandbox.
- Verifier eval: a fixed set of indirect hops from the target repos (real ones and planted fake ones). Measure how many real hops it rejects (must be near zero) and how many fake hops it catches.
- Pipeline tests run on recorded model calls.
- **Golden eval:** codemap's own trace pipeline, traced from the `trace` CLI command to the saved graph.
  - **The code is ground truth, not the docs.** Design documents can describe stages the code does not have.
  - **Expected output (my call):** the builder writes `evals/codemap-trace.expected.json` by reading the code. It lists phases and steps with `file:line` spans and the expected effects. The user reviews it once before it is used.
  - **Expected shape (my call):** phases follow the code's execution units (the CLI command, then each pipeline stage). If resolve, walk and split run in one function, they are steps inside one phase.
  - Scored on the two anti-goals: nodes not on the path, and splits that disagree with the code's stages.
- **Model compatibility (builder verifies first):** forced tool choice / structured output, parallel tool calls, usage fields. If structured output is not supported, use parse-and-validate with retry. If cost is not returned, compute it from a pricing table in code.

## 12. Structure and production setup

Reference tools: marimo, Arize Phoenix and Langflow (a Python package that ships a built React UI inside the wheel), and simonw's `llm` and Datasette (CLI tools with a local SQLite store).

### 12.1 File tree

```text
codemap-v2/
  pyproject.toml              # hatch; a build hook bundles frontend/ into the wheel
  Makefile                    # dev, build, check, eval
  .importlinter               # layer contracts (§12.2)
  src/codemap/
    __main__.py               # python -m codemap
    settings.py               # pydantic-settings: env > ~/.config/codemap/config.toml > defaults
    logs.py                   # rotating log file in <repo>/.codemap/logs/
    service.py                # the one app API: start_trace, expand_node, list_traces, get_detail
    cli/                      # Typer + Rich; no logic, calls service.py
      main.py                 # root app, global flags (--verbose, --repo)
      trace.py                # codemap trace  (resolve → confirm prompt → run → open browser)
      open.py                 # codemap open
      doctor.py               # codemap doctor: env, model endpoint, ripgrep, db, version
      render.py               # live progress from events
    domain/                   # pure: no IO, no model, no DB
      models.py               # Trace, Node, Edge, Effect, Hop, Anchor (pydantic)
      rules.py                # path checks, in/out checks, effect rollup
      events.py               # progress event types
    pipeline/                 # fixed steps (§6), one file per step
      run.py  resolve.py  walk.py  verify.py  split.py  detail.py  validate.py
    agents/                   # generic agent machinery, knows nothing about codemap
      loop.py                 # tool loop
      model.py                # provider SDK (OpenAI or Anthropic)
      limits.py               # run limits → partial
      recording.py            # record / replay
    prompts/                  # one .md per agent prompt
    repo/                     # read-only access to the target repo
      tools.py  ignore.py  index.py  anchors.py
    store/
      db.py                   # sqlite3, WAL mode, migration runner (PRAGMA user_version)
      migrations/0001_init.sql
      traces.py               # queries
    server/                   # FastAPI, thin; calls service.py
      app.py  routes.py  sse.py  schemas.py
      static/                 # built frontend; not in git, in the wheel
  frontend/                   # Vite + React + TS
    src/
      main.tsx  App.tsx
      api/                    # client + types generated from the server's OpenAPI
      state/                  # zustand store: open nodes, selection, filters
      canvas/                 # FlowCanvas, PhaseNode, StepNode, edges, layout.ts (elkjs)
      panels/                 # DetailPanel, EffectPanel
      effects/                # EffectLane, EffectChip, categories.ts
      Toolbar.tsx
  tests/
    unit/                     # domain, repo tools, store
    pipeline/                 # full runs on recorded model calls
    server/                   # API tests
  frontend/tests/             # vitest; one playwright smoke test of expand/collapse
  evals/                      # golden traces + scorer + verifier hop set
  docs/specs/
```

### 12.2 Layer rules (enforced by import-linter)

```text
cli, server  →  service  →  pipeline  →  domain, agents, repo, store
```

- `domain` imports nothing from codemap.
- `agents` does not import `pipeline`, `domain`, `store` or `server`.
- `cli` and `server` import only `service` and `domain` (and `server` imports `settings`).

### 12.3 Runtime shape

- **One process.** `codemap trace` runs the pipeline in-process and starts uvicorn on a free local port, bound to `127.0.0.1` only. CLI progress and SSE read the same event stream.
- `service.py` is the only entry used by both the CLI and the server. Lazy expand from the UI uses the same code path as a CLI trace.
- Ctrl-C or a crash marks a running trace `partial` with its work kept. On start, codemap marks old `running` rows `partial`.
- HTTP API is versioned under `/api/v1`.

### 12.4 Production setup

- **Install:** `uv tool install codemap` or `pipx install codemap`. The wheel includes the built UI, so Node is not needed at install time.
- **Dev:** `make dev` runs FastAPI and the Vite dev server (proxy to the API) with hot reload.
- **Config:** env vars override the user config file, and the user config file overrides defaults. Secrets come only from env or the config file. Secrets are never logged or stored in the DB. Paths come from `platformdirs`.
- **SQLite:** stdlib `sqlite3`, WAL mode, plain SQL migrations numbered by `PRAGMA user_version`. No ORM, because SQLite is the only DB.
- **Schemas:** pydantic models validate model output and API payloads. TypeScript types are generated from OpenAPI (`openapi-typescript`), so the frontend and backend cannot drift.
- **External binaries:** ripgrep is preferred. If ripgrep is missing, search falls back to a Python implementation, and `codemap doctor` warns.
- **Quality gate (`make check`):** ruff, mypy strict, import-linter, pytest, frontend typecheck and vitest.
- **Versioning:** semver; `codemap --version`; the DB schema version is checked on start.
- **Frontend state (my call):** one `zustand` store, because the canvas, toolbar, panels and lane share state.
- **Code style:** small files with one concern each, small functions, standard Python and React idioms, no speculative abstraction.

## 13. Left to the builder

- Exact SQLite schema and table names.
- Prompt wording, within the rules in §5.
- Concurrency and limit default values.
- Visual styling of the canvas, within the approved behaviour in §9.2.
- The tree-sitter package choice.
