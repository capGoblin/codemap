# codemap

Trace one system in a codebase into a graph you can zoom into.

You name a system ("the checkout flow", "how a request is authenticated") or an entry point. codemap follows the real code path with an LLM agent, cuts it into the system's stages, and shows them in a browser canvas. Open a stage to see its steps. Open a step to see its sub-steps, down to the code. Every node shows what it reads and writes: database tables and fields, object stores, queues, caches, files and HTTP calls.



https://github.com/user-attachments/assets/5ba84fca-c8b6-4546-ab5d-07b4e96d1289



*codemap tracing its own pipeline: `codemap trace "How does codemap trace a system, from the trace command to the saved graph?"`*

- **Any language.** tree-sitter grammars are bundled, and files without a grammar fall back to plain search.
- **Real hops only.** A separate verifier agent checks each indirect hop (string dispatch, registries, queues, callbacks) before it goes in the graph.
- **Local.** Traces live in SQLite inside the repo (`.codemap/`). The UI server binds `127.0.0.1`. The only data that leaves your machine is the model call.
- **Bring your own key.** OpenAI or Anthropic, with a cost cap on every run.

## Install

You need Python 3.12+ and [uv](https://docs.astral.sh/uv/). Node.js 20+ is needed only to build the UI when you install from source. [ripgrep](https://github.com/BurntSushi/ripgrep) is optional, but it makes code search faster.

```bash
uv tool install git+https://github.com/capGoblin/codemap
codemap --version
```

## Set your API key

codemap uses OpenAI `gpt-5-nano` by default. It is cheap, and a full trace usually costs a few cents.

```bash
export OPENAI_API_KEY=sk-...          # OpenAI (default)
# or
export ANTHROPIC_API_KEY=sk-ant-...   # Anthropic, with --provider anthropic
```

Check the setup:

```bash
codemap doctor
```

The doctor checks the key, the model price, ripgrep, the database and one live model call. It never prints the key.

## Trace a system

Go to the repo you want to understand, and ask about one system:

```bash
cd path/to/your/repo
codemap trace "How does an uploaded file get parsed and stored?"
```

1. codemap finds candidate entry points and asks you to pick one (`--pick 1` skips the prompt).
2. It walks the code path, verifies indirect hops, and builds the stages and two levels of steps.
3. It opens the graph in your browser. Ctrl-C stops a run early and keeps a partial trace.

You can also give the entry point directly, as `file:Symbol`:

```bash
codemap trace "src/api/upload.py:UploadView.post"
```

### Lazy mode

A full trace builds every level up front. With `--lazy`, codemap builds only the stage level, and each node's steps are built when you open it in the UI. It is faster and cheaper on big systems.

```bash
codemap trace "How does billing run at month end?" --lazy
```

### See your traces

```bash
codemap list              # every trace in this repo: id, question, status, cost, date
codemap open <TRACE_ID>   # open one in the browser
codemap open              # no id: list traces, then open one
```

### Other trace options

| Option | Does |
| --- | --- |
| `--pick N` | Use entry point N, with no prompt |
| `--lazy` | Build the stage level only. Deeper levels are built on click |
| `--no-open` | Do not start the browser or the server |
| `--json` | Print the graph JSON on stdout (for scripts) |

## Models, keys and cost

Global options go **before** the command:

```bash
codemap --provider anthropic --model claude-sonnet-5-5 --max-cost 1.50 trace "..."
```

| Option | Env var | Default |
| --- | --- | --- |
| `--provider` | `CODEMAP_PROVIDER` | `openai` |
| `--model` | `CODEMAP_MODEL` | `gpt-5-nano` (OpenAI), `claude-haiku-5-5` (Anthropic) |
| `--api-key` | `CODEMAP_API_KEY`, else `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | none |
| `--base-url` | `CODEMAP_BASE_URL` | the provider's API |
| `--max-cost` | `CODEMAP_MAX_COST` | `5.0` USD per run |
| `--repo` | | current directory |

Order of priority: flags, then env vars, then the config file, then defaults.

- **`--api-key` works, but use the env var if you can.** A key passed as a flag stays in your shell history.
- **`--base-url`** points codemap at any OpenAI- or Anthropic-compatible endpoint, for example a proxy or a local server.
- **Cost.** codemap knows the prices of the common OpenAI and Anthropic models. For any other model, set `price_in_per_mtok` and `price_out_per_mtok` in the config file. If it can't find a price, it can't enforce `--max-cost`, and `codemap doctor` warns you.
- **Free re-runs.** Every model call is cached in the repo's database, so an identical request costs nothing the second time.

### Config file

Put defaults in `config.toml`. Run `python -c "import platformdirs; print(platformdirs.user_config_dir('codemap'))"` to find its folder. You can also point `CODEMAP_CONFIG_FILE` at a file of your own.

```toml
provider = "anthropic"
model = "claude-haiku-5-5"
max_cost_usd = 2.0
```

## Using the UI

- **Click a node** to open it in place into its steps, and to show its Details in the right panel. No page changes, no breadcrumbs.
- **Details** teach the node: how it works (each step cites lines), input, output, data touched, calls, and the code. They are built the first time you open them.
- **Data touched** tab: every table, bucket, queue and file the trace reads or writes. Click one to highlight the nodes that touch it.
- **Toolbar:** expand all, collapse all, fit, filters.
- Dashed edges are async hand-offs (queues, background jobs, events). Dimmed nodes are error and side paths.

## What it stores and what it reads

- **Stored** in `<repo>/.codemap/codemap.db`: traces, nodes, edges, hops, effects, run events and cached model calls. codemap adds `.codemap/` to `.git/info/exclude`.
- **Not stored:** your source code or API keys. Code is read from disk when it is needed. A node goes stale when its code changes.
- **Never read:** git-ignored files, dependencies, build output, binaries and secrets (`.env*`, keys, `.npmrc`, `.netrc`, `credentials*`, `.aws/`, `.ssh/`, `*.tfvars`…). The agent has read-only tools and no shell.

## How it works

```text
question → find entry → walk stages → verify indirect hops → split into stages
        → expand calls (tree-sitter) → find effects → split into steps → validate → save
```

See [docs/guide](docs/guide/README.md) for the full walk-through: the pipeline, the data model, the server and the UI.

## Develop

```bash
uv sync
npm --prefix frontend ci
make check     # ruff, mypy strict, import-linter, pytest, frontend typecheck + vitest
make dev       # API on 127.0.0.1:8765 + Vite dev server
```

Evals run codemap against its own pipeline:

```bash
make eval                                  # golden trace of codemap itself (replays recorded calls)
uv run python -m evals.run_golden --record # real model calls
uv run python -m evals.run_smoke evals/smoke.json   # one trace per repo in the file
```

Add your own repos to `evals/smoke.json` to smoke-test codemap on them.

## License

MIT
