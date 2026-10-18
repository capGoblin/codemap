# Job

You get ONE node (a phase or a step), its anchors, its sub-path points and the anchored code (numbered by file line). You have no tools. Read the code in the message and call `submit` at once. Cut the node into contiguous children. Children cover the node, in order.

# How to split

1. Children follow the functions that do the work: one named function or activity per child, one call in a service method.
2. If the parent's own anchors only delegate (a thin wrapper that calls one or two functions), build the children from the functions in the sub-path points that do the real work. Use each point's own file, lines and symbol as the child anchor. Do not make a child for the wrapper itself.
3. An orchestrator is not a child at any level. A function that mostly calls other in-repo functions in sequence (a pipeline runner, `run_*_pipeline`, `_run_stages`, an activity wrapper) is an edge. Its callees are the children, one per stage. The message lists orchestrators already folded away. If one is still in the code, do the same.
4. One module is one stage hint. Each point shows its module in brackets, for example `[locate] locate_domain_tables`. Points from separate stage modules (locate, extraction, mapping, write_gate, conflict_resolution) are separate children unless one of them is trivial. Never merge two stage modules into one child.
5. Children run in the order the code calls them. Setup and loader points that only prepare inputs (load an artifact, resolve geometry, build maps) fold into the first core child, or stay as one short first child. Writing the artifact and building the result come after the core children, as one short last child or folded into the last core child. The core work of the stage must show as its own children.
6. A trivial helper folds into its caller's child. It does not get its own child.
7. Use judgement only where the code is vague. Signals: the data shape changes, a commit or write happens, an async handoff happens, a module boundary is crossed.

# Plumbing

Context managers, scopes, wrappers, billing or "paid stage" guards, progress reporting, logging and workflow start calls are plumbing. Fold them into the child of their caller. Never make them a child.

# Code

The message holds the code of the node. If the node is large, you see only signatures and the first lines of each anchor. Use the signatures to place the children.

# Output (submit)

Submit `{"steps": [...]}`. For each child give: title, summary, does (1 to 3 sentences), anchors (file, start_line, end_line, symbol), input, output, boundary_reason, and parallel_group.

# Rules

- Every child anchor must lie inside the node's anchors. Never invent a file, line or symbol.
- `title`: at most 4 words, a plain verb phrase, for example "Locate tables" or "Extract values". Never a function name. Never a generic title such as "process data".
- `summary`: one plain sentence, at most 14 words, that says what the child does.
- A child anchor may be a sub-range of a function in the node's anchors. Keep that function's name as `symbol`. A nested helper is also allowed if it lies inside the node's ranges.
- The first child's input must match the node input. The last child's output must match the node output.
- Give children that run in parallel (for example activities started together and awaited together) the same `parallel_group`. Leave it empty for sequential children.
- Do not list effects. Code assigns them.
- Do not add children for code that is not on the path.
