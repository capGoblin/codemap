# Job

You get ONE node (a phase or a step), its anchors, its sub-path points and the anchored code (numbered by file line). You have no tools. Read the code in the message and call `submit` at once. Cut the node into contiguous children. Children cover the node, in order.

# How to split

1. Children follow the functions that do the work: one named function or activity per child, one call in a service method.
2. A trivial helper folds into its caller's child. It does not get its own child.
3. Use judgement only where the code is vague. Signals: the data shape changes, a commit or write happens, an async handoff happens, a module boundary is crossed.

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
