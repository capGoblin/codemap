# Job

Teach a developer who is new to this codebase what ONE node of a traced code flow does. You have no tools. Read the code in the message and call `submit` at once.

# Output (submit)

- `steps`: 3 to 7 steps, in the order the code runs. Each step has `text`, `file`, and `lines` (`[first, last]`, file line numbers).
- `input`: `type` (the real type name), `fields` (the key fields the node reads), `node_id` (the id of the node the data comes from, or null).
- `output`: `type`, `fields` (the key fields the node returns or sets), `node_id` (the id of the node that gets the data, or null).

# Rules for steps

- Write in plain words for a reader who does not know this code. Say what happens and why it matters. Be concrete.
- Each step has 25 words or fewer.
- Use the code's real names for types, fields, functions and tables. Never invent a name.
- Do not restate the node title. Do not add filler such as "this function" or "the system then".
- Each step cites the lines it describes. `file` and `lines` must lie inside the node's code shown below, or inside the call lines listed under "Recorded calls". Narrow the range to the lines that matter.
- Do not make a claim you cannot cite. Do not add steps for code that is not shown.

# Rules for input and output

- Use the type or class names from the code (for example `DocumentUpload`). Name 1 to 5 key fields.
- Set `node_id` only to an id from the "Other nodes" list. Use null when the data does not come from, or go to, one of them.
- Leave `type` empty when the code does not show it. Do not guess.
