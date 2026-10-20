---
name: codemap
description: Trace one flow through a codebase and write it as a cited markdown map (Mermaid diagram plus stages with steps, reads and writes). Use when the user asks how a flow, feature or system works in a repo ("how does X work", "trace X", "map what happens when Y"), or wants a flow doc for onboarding, a PR review or AI-written code.
---

# Codemap

Writes `docs/flows/<slug>.md`: a map of ONE flow in which every claim cites code. Read-only on the repo, except for that one file.

## Rules

1. **Cite only what a tool showed you in this session.** Copy `path:lines` from Read or `grep -n` output. Never write a line number from memory.
2. **A claim with no citation is not written.** The script rejects it.
3. **Do not drop a real hop on a hunch.** If you cannot prove a hop, keep it and mark it ⚠️ unsure.
4. **Stage level first.** 3 to 7 stages. Step over plumbing (auth, logging, retries, getters).
5. **Secrets stay out.** Never open `.env*`, keys, or git-ignored files. Never copy a secret value into the file.
6. **Be honest in the card.** Write `partial` and the reason if you stopped early or left hops unsure. Put doubts in the card's Doubts row.

## Steps

- [ ] **1. Scope.** Find 2 to 5 entry points with `grep` and the outline (routes, commands, handlers, jobs). Prefer the outermost handler. If the user did not name one, ask them to pick. Run `git rev-parse HEAD` and `git status --porcelain`.
- [ ] **2. Walk.** From the entry, follow the flow at stage level. For each hop note caller, callee, kind (`call`, `async`, `error`, `branch`) and the line that proves it. Stop at the end of the flow, at a third-party library, or after 40 hops (ask before going further).
- [ ] **3. Type each hop.** Direct: the callee's name is in the caller's lines (`grep -nw`). Anything else is indirect: a queue, a registry, a string dispatch, a callback. For an indirect hop, read the wiring yourself and follow it to where it is registered. Cite the wiring in the Evidence cell. If you cannot find the full chain, mark the hop ⚠️ unsure.
- [ ] **4. Shape it.** Cut the flow into 3 to 7 stages, with one level of steps inside each. Note each read and write with the line that does it.
- [ ] **5. Draft** the file from [TEMPLATE.md](TEMPLATE.md).
- [ ] **6. Run the check:** `python3 scripts/cite.py check <file>`. It is free. Fix every FAIL.
- [ ] **7. Tell the user** the path, the status, and the top doubts.

`scripts/` is in the folder that holds this SKILL.md.

## Choices already made

- Output: `docs/flows/<slug>.md`. Create the folder if needed.
- Links: GitHub permalinks with the commit sha when `git remote get-url origin` is a GitHub URL. Otherwise relative links.
- Depth: stages plus one level of steps.

## Strict mode (only when the user asks)

If the user wants a verified trace, also follow [RELIABILITY.md](RELIABILITY.md): a separate subagent checks each indirect hop. Do not run it by default. It costs the user's subscription.

## Not in scope

No edits to the repo, no running the code under study, no network calls. A flow that leaves the repo ends there, and the card says so.
