# Job

You get the ordered points of a recorded execution path, one per line: `index: file:start-end symbol`. Cut the path into the system's real stages (phases). Phases are contiguous, in order, with no gaps and no overlap. A phase may span many points.

# What a phase is

- A phase is a major stage of the system: a workflow activity, a pipeline stage, a service boundary. Typical count 3 to 6. Hard cap 7.
- Plumbing is never its own phase: auth, request validation, idempotency keys, dedupe, outbox relay, workflow/job runners, run bookkeeping, status updates, retries. It becomes a step inside the phase it serves, or is left out when trivial.
- An orchestrator (workflow `run`, job runner, router, pipeline runner) is not a node. Its order becomes the edges between phases.
- Plumbing points are folded into the neighbouring phase they serve. They do not get a span of their own.

# Example (generic)

Path: an HTTP upload handler, an idempotency check, an async scan callback, an outbox write, a job start, a job runner, then three functions that parse, enrich and save a record.

- Wrong: 7 phases, one per function. That lists plumbing.
- Right: "Receive" (handler, idempotency check, async scan callback, outbox write, job start), "Parse", "Enrich", "Save". The job runner is not a phase. Its order is the edges.

# How to split

1. Follow the code's own structure first: workflow and activity definitions, pipeline stage modules, named functions that do one stage of the work.
2. Use your judgement only where the code is vague. Signals: the data shape changes, a commit or write happens, a module or service boundary is crossed.

# Output (submit)

For each phase give: title, summary, does (1 to 3 sentences), `start` and `end` (the first and last path index), input (data type and key fields), output (data type and key fields), and boundary_reason (why the phase starts and ends here).

# Rules

- Use only indexes and anchors from the given path. Never invent a file, line or symbol.
- `title`: at most 4 words. A verb phrase or the stage's own name, for example "Upload" or "Locate tables". Never a function name. Never a generic title such as "process data".
- `summary`: one plain sentence, at most 14 words, that says what the phase does.
- The output of one phase should match the input of the next, or boundary_reason must say why not.
- Do not add a phase for code that is not on the path.
- Prefer fewer, clear phases over many thin ones. A phase is one stage of work, not one function call.
- An async handoff that only moves the same work along (upload -> scan callback -> queue -> job start) stays inside one phase. A phase boundary is where the system starts a new stage of work on the data.
