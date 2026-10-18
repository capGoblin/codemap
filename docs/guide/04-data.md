# 04 — Data

## Domain models — `src/codemap/domain/models.py`

| Model | Fields |
| --- | --- |
| `Anchor` | `file`, `start_line`, `end_line`, `symbol`, `content_hash` |
| `Effect` | `category` (db, object_store, queue, cache, file, workflow, http, other), `target`, `op` (read/write), `fields[]`, `anchor` |
| `Hop` | `id`, `caller`, `callee`, `kind` (call/async/error/branch), `hop_type` (direct/indirect), `wiring`, `verdict` (code_checked/confirmed/unsure/rejected), `evidence` |
| `Node` | `id`, `level`, `parent_id`, `order`, `title`, `summary`, `does`, `input`, `output`, `boundary_reason`, `anchors[]`, `effects[]`, `parallel_group`, `stale`, `warnings[]` |
| `Edge` | `source_id`, `target_id`, `kind` |
| `Trace` | `id`, `question`, `entry`, `commit_sha`, `dirty`, `status`, `mode`, `created_at`, `model`, `input_tokens`, `output_tokens`, `cost_usd` |
| `NodeExplain` | `steps[]` (`text`, `file`, `lines`), `input` / `output` (`type`, `fields[]`, `node_id`) |
| `NodeDetail` (API) | `explain`, `explain_error`, `functions[]` (`FunctionDetail`), `calls[]` (`symbol`, `node_id`), `effects[]` |
| `Event` (`events.py`) | `trace_id`, `kind` (step_started, hop_found, hop_verified, phase_split, warning, finished), `message`, `data`, `at` |

## SQLite — `<repo>/.codemap/codemap.db`

Schema: `store/migrations/0001_init.sql`, `0002_v21.sql` (+ Python post-step in `store/db.py`). Version in `PRAGMA user_version` (now 2). WAL mode, one `RLock` per connection.

| Table | Fields | Written by | Read by |
| --- | --- | --- | --- |
| `traces` | `id`, `question`, `entry` (JSON), `commit_sha`, `dirty`, `status`, `mode`, `created_at`, `model`, `input_tokens`, `output_tokens`, `cost_usd` | `Service.start_trace` (W), `run_trace` (W status/totals), `Service()` start (W running→partial) | CLI `open`, API `/traces` |
| `nodes` | `trace_id`, `id`, `level`, `parent_id`, `ord`, `title`, `summary`, `does`, `input`, `output`, `boundary_reason`, `anchors` (JSON), `effects` (JSON), `parallel_group`, `stale`, `warnings` (JSON) | `run_trace` (W phases early, children per parent, final replace), `expand_node` (W children), `get_graph` (W `stale`) | API graph, explain, detail |
| `edges` | `trace_id`, `source_id`, `target_id`, `kind` | `run_trace`, `expand_node` | API graph |
| `hops` | `seq`, `trace_id`, `hop` (JSON `Hop`) | walk (W each hop as recorded), bridges, static expand | split, validate, explain, expand, evals |
| `walk_effects` | `seq`, `trace_id`, `effect` (JSON `Effect`) | walk `record_effect`, `phase_effects` | split (assign), expand, explain |
| `events` | `id`, `trace_id`, `event` (JSON `Event`) | every stage via `ctx.emit` | CLI progress, SSE stream |
| `node_details` | `trace_id`, `node_id`, `explain` (JSON `NodeExplain`), `created_at` | `Service.get_detail` / `regenerate_detail` | `Service.get_detail` |
| `model_calls` | `key` (sha256 of request), `response` (JSON) | `CachedModel` | `CachedModel` (identical request → no API call) |
| `symbols` | `content_hash`, `symbols` (JSON outline) | `SymbolIndex` | `SymbolIndex` |
| `verdicts` | `key`, `verdict`, `evidence`, `suggested` | `verify_hop` | `verify_hop` |

Never stored: source code, file contents, API keys/tokens. Code is read from disk via anchors when needed; staleness = anchor hash changed.

## Other files on disk

| Path | What |
| --- | --- |
| `<repo>/.codemap/logs/codemap.log` | rotating log, token redacted |
| `<repo>/.git/info/exclude` | gets one line `.codemap/` |
| `~/.config/codemap/config.toml` | optional user config |
| `evals/recordings/*.json` | recorded model calls for free replay (git-ignored) |
