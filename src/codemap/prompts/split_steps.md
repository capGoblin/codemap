# Job

You get ONE phase and its anchors, the ordered path points inside it (`index: file:start-end symbol`). Cut the phase into contiguous steps. Steps cover the phase, in order.

# How to split

1. Follow the code's own structure first: one named function or activity per step, one call in a service method, one repository call.
2. Use judgement only where the code is vague. Signals: the data shape changes, a commit or write happens, an async handoff happens, a module boundary is crossed.

# Tools

Use `read_file` with short ranges, `outline` or `search` only to check a boundary. Keep it small. The path points are usually enough.

# Output (submit)

For each step give: title, does (1 to 3 sentences), anchors (file, start_line, end_line, symbol), input, output, boundary_reason, and parallel_group.

# Rules

- Every step anchor must lie inside the phase's anchors. Never invent a file, line or symbol.
- Titles use the code's own names. No generic titles such as "process data" or "handle logic".
- The first step's input must match the phase input. The last step's output must match the phase output.
- Give steps that run in parallel (for example activities started together and awaited together) the same `parallel_group`. Leave it empty for sequential steps.
- Do not list effects. Code assigns them.
- Do not add steps for code that is not on the path.
