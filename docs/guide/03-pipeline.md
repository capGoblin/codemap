# 03 — Pipeline stages

All in `src/codemap/pipeline/`. Every model call goes through `agents/loop.py:run_tool_loop` (tools + a `submit` tool validated by a pydantic schema; invalid submit → error text back to the model; limits checked before each call).

## Shared context — `context.py`

`TraceContext`: repo root, `RepoTools` (+ index), model (cached), `walk_budget`, `build_budget`, store, verdict cache, settings, `emit`, trace id, cancel event. `build_context()` makes one per thread (own DB connection). `read_tools()` = the 5 read-only tools every agent gets: `list_dir`, `read_file` (400-line pages), `search` (ripgrep), `find_definition`, `outline`.

## Stages

| Stage | File | Model? | In → Out | Key rules |
| --- | --- | --- | --- | --- |
| Resolve | `resolve.py` | agent loop (or none for `path:Symbol`) | question → `EntryCandidate[]` | anchors checked + hashed; model error raises (never "no entry point"); limit → `ResolveLimitError` |
| Skeleton walk | `walk.py` | agent loop, budget `skeleton_hops`=40 | entry → hops + effects | stage level only; plumbing skipped; handoffs recorded as `async` indirect hops with wiring anchor; tools `record_hop`, `record_effect` |
| Verify | `verify.py` | fresh agent per indirect hop, sees only the claim | hop → `confirmed / unsure / rejected` | reject needs evidence text + valid anchor, else `unsure`; transitive chains through plumbing are not rejected; cached by hop identity |
| Order points | `domain/rules.py:ordered_points` | no | hops → points + bridges | overlap-based anchor identity; islands bridged, never dropped |
| Split phases | `split.py:split_phases` | 1 structured call | points → level-0 nodes | 1–7 phases; contiguous spans; title ≤ 4 words, not a bare function name; summary ≤ 14 words; code sets anchors + effects |
| Static expand | `expand.py` | no | phase → `code_checked` hops | tree-sitter call sites (`repo/calls.py`); definition pick: same file → imported file → nearest dir; in-repo only, never ignored files; larger callees first |
| Deepen fallback | `walk.py:walk_deepen` | agent loop | phase → hops | only when static finds < 3 points; hops must stay inside the phase; equal budget + carry-over |
| Phase effects | `effects.py` | 1 call per phase | expanded code → effects | R/W only; target normalised (`domain/rules.py:normalize_target`); line must lie in an expanded point |
| Split children | `split.py:split_children` + `orchestrators.py` (`flatten_points`) | 1 call per parent (threads) | parent + reachable points → children | orchestrators collapsed into callees; `[module]` stage hints; trivial helpers fold; last turn trims long titles instead of failing |
| Side nodes | `split.py:side_nodes` | no | error/branch hops → dimmed nodes | one hop deep |
| Validate | `validate.py` | no | nodes → kept nodes + warnings | anchor + symbol check (range-only for sub-ranges); off-path dropped with reason; recursive effect rollup |
| Expand on demand | `run.py:expand_node` | split (+ 20-hop deepen if < 3 points) | any node → children | used by UI click and lazy mode |
| Explain | `explain.py` | 1 call, no tools | node code + hops + effects → `NodeExplain` | 3–7 steps, each cited; cites outside the node dropped; stored in `node_details` |
| Detail (code) | `detail.py` | no | node → `FunctionDetail[]` | full code from disk, signature, calls |

## Prompts — `src/codemap/prompts/`

`resolve.md`, `walk_skeleton.md`, `walk_deepen.md`, `verify.md`, `split_phases.md`, `split_steps.md`, `phase_effects.md`, `explain.md`.
