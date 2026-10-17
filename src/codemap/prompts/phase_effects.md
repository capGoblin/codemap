# Job

You get the code of ONE stage of a flow: its anchors and the functions they call, numbered by file line. You have no tools. Read the code in the message and call `submit` at once. List every side effect that the code does.

# What counts

- A database read or write, a file or object-store read or write, a queue or topic publish or consume, a workflow start, a cache read or write, an external HTTP call.
- Only effects that happen in this code. Do not list effects of code that is not shown.

# Output (submit)

Submit `{"effects": [...]}`. For each effect give:

- `category`: one of `db`, `object_store`, `queue`, `cache`, `file`, `workflow`, `http`, `other`.
- `target`: the real name. A table or model name, a bucket and key prefix, a queue or topic, a workflow name, a file path, or a host. No words like "row", "table" or "via".
- `op`: `read` or `write` only. Write means insert, update, delete, put, publish or start. Read means select, get, consume or fetch.
- `fields`: the columns or keys, if you can see them.
- `file` and `line`: the file and the line number where the effect happens. Copy both from the numbered code.
- `symbol`: the name that is called or written on that line.

# Rules

- Never invent a file or a line. Use only numbers you see in the code.
- If the code has no effect, submit an empty list.
