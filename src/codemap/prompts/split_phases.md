# Job

You get the ordered points of a recorded execution path, one per line: `index: file:start-end symbol`. Cut the path into contiguous phases. Phases cover the whole path, in order, with no gaps and no overlap.

# How to split

1. Follow the code's own structure first: workflow and activity definitions, pipeline stage modules, handler to service to repository layers, named functions that do one stage of the work.
2. Use your judgement only where the code is vague. Signals: the data shape changes, a commit or write happens, an async handoff happens, a module or service boundary is crossed.

# Output (submit)

For each phase give: title, does (1 to 3 sentences), first and last path index, input (data type and key fields), output (data type and key fields), and boundary_reason (why the phase starts and ends here: name the code structure or the signal).

# Rules

- Use only indexes and anchors from the given path. Never invent a file, line or symbol.
- The title says what the stage does, in a few words, with the code's names. You may add the code name in parentheses, for example "Recall memories (gated_retrieve)" or "Log the exchange (log_chat)". Never use a bare function name as the title. Never use generic titles such as "process data" or "handle logic".
- The output of one phase should match the input of the next, or boundary_reason must say why not.
- Do not add a phase for code that is not on the path.
- Prefer fewer, clear phases over many thin ones. A phase is one stage of work, not one function call.
- Keep async handoffs at a phase boundary.
