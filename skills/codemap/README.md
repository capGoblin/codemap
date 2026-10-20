# codemap (skill)

Ask how a flow works in a codebase. Get one markdown file with a diagram, the stages, and a link to the code for every claim.

This is a skill for coding agents such as Claude Code. It runs on the subscription you already have. It needs no API key and no server.

See a finished one: [examples/codemap-pipeline.md](examples/codemap-pipeline.md).

## Install

In Claude Code:

```
/plugin marketplace add https://github.com/capGoblin/codemap.git
/plugin install codemap@codemap
```

For Codex, Cursor and other agents that use the skills CLI:

```bash
npx skills add capGoblin/codemap
```

Then, in your repo:

```
> trace how a request gets authenticated
```

The agent finds entry points and asks you to pick one. It writes `docs/flows/<name>.md`.

## What the file holds

Four sections: the answer, a trace card (status, hop counts, doubts), a Mermaid map, and one block for each stage with its steps, calls and reads and writes. The layout is in [TEMPLATE.md](TEMPLATE.md).

## How it stays honest

- Every claim cites lines the agent read in that session.
- `scripts/cite.py check` re-opens every cited range and checks the file, the lines, the named function, the section layout and that no secret is in the text. It is free: it runs no model.
- Hops the agent could not prove stay in the map as ⚠️ unsure, and the card names them.
- Ask for a strict trace and a separate subagent checks each indirect hop. See [RELIABILITY.md](RELIABILITY.md).

## The checker

Python 3, standard library only.

```bash
python3 scripts/cite.py check docs/flows/auth.md
```

## Limits

- The skill has no tree-sitter. It follows calls by reading and with `grep`, so it can miss calls a parser would find.
- A big flow costs a lot of your subscription's usage. The skill stops at 40 hops and asks.
- A trace can still be wrong. The check proves that the lines exist and the names match. It does not prove a sentence is true.
- It traces one repo. A flow that leaves the repo ends at the boundary.
