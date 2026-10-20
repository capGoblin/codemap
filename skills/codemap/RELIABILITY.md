# Reliability

The default run needs no subagents. It relies on three things: citations come from tool output, `scripts/cite.py check` re-opens every cited range, and you test each indirect hop yourself. This file says how to do that well, and how to run the stricter mode.

## What the script checks

- The cited file exists inside the repo, and is not ignored by git or a secret file.
- The cited lines exist, and a symbol in the link title appears in the range.
- Every numbered claim in Answer and Stages has a citation.
- The sections are the ones in the template, and there is a Mermaid diagram.
- The text holds no key-like string.

It does not check that a sentence is true. That is on you.

## Check an indirect hop yourself

1. Read the caller range. Find the call, dispatch, publish or start.
2. Follow the wiring: the string, registry key, decorator, route, DI binding, queue or event name. Find where it is registered and what it maps to.
3. Is the registered target your callee? Yes: cite the wiring in the Evidence cell. Cannot tell: mark the hop ⚠️ unsure. Never drop the hop only because you cannot prove it.
4. A hop that skips plumbing (A reaches B through validation, an outbox or a runner) is still a hop. Keep it.

## Things that fool you

- A name in a comment or a string matches `grep -w` but is not a call. Read the line.
- Two functions with the same name in different files. Check which one is imported.
- A route table that registers a handler under a string. The string is the wiring. Cite it.
- Code behind a flag or in a test-only branch is not part of the flow.
- A mock or a fake with the same name as the real thing. Open the file.
- A sentence that is stronger than its lines. If a number or a condition is not in the cited lines, cite it or leave it out.

## Status

- `complete`: every stage has a citation and no hop is unsure.
- `partial`: you hit the hop limit, the user stopped you, or hops are unsure. Write the reason in the card.
- `failed`: no stage survived. Do not write the map. Tell the user what blocked you.

## Strict mode

Use it only when the user asks for a verified trace. Launch one fresh subagent per indirect hop, in parallel. Give it ONLY this, filled in. Do not share your reasoning or the question.

> Check ONE claim: "the caller leads to the callee". You may read files and search the repo. You may not edit anything.
> Caller: `<path:start-end> symbol`
> Callee: `<path:start-end> symbol`
> Kind: `<call|async|error|branch>`
> Wiring cited: `<path:start-end>` or none
>
> 1. Read the caller range and find the call, dispatch, publish or start that could reach the callee.
> 2. Do not trust the cited wiring line until you have read it. Follow the string, registry key, decorator, route, DI binding, queue or event name to where it is registered.
> 3. Check that the registered target is the callee.
>
> Answer with: `verdict` (confirmed, unsure or rejected), `evidence` (short, with `path:line` for each line you used), and `suggested_callee` if you found the real one. Reject only with code you read yourself and quote. If you cannot prove or disprove it, answer unsure and say what is missing. Be short.

Rules for the verdict:

- `confirmed`: it found the whole chain and cites the lines.
- `unsure`: the default when it cannot prove or disprove the hop.
- `rejected`: only when it quotes code that shows a different target. Without that, treat it as `unsure`.
- A lost real hop costs more than a kept wrong one.

Set `Checked by` in the card to say a subagent did it. No audit subagent is needed. If the user wants one, ask a fresh subagent to re-open the cited lines and report sentences that say more than the lines show. One round is enough.
