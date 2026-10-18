# Contributing

Thanks for helping. Bug reports, small fixes and new ideas are all welcome.

## Set up

```bash
uv sync
npm --prefix frontend ci
make check
```

`make check` runs ruff, mypy (strict), import-linter, pytest and the frontend typecheck and tests. Run it before you open a pull request.

## Project rules

- **Layers.** Code flows one way: `cli → server → service → pipeline → store / repo / agents → domain`. import-linter enforces this. See [docs/guide](docs/guide/README.md).
- **No private data in tests, docs or evals.** Use this repo or `tests/fixtures/sample_repo`.
- **No real model calls in tests.** Use the scripted fakes in `tests/fakes.py`.
- **Keep changes small.** One idea per pull request. Add a test for each fix.

## Run the UI in dev mode

```bash
make dev
```

This starts the API on `127.0.0.1:8765` and the Vite dev server.

## Report a bug

Open an issue with the command you ran, the model you used and the output of `codemap doctor`. Never paste an API key.
