# codemap v2.1 — Plan 4: Shape, depth, clarity

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Traces come out as the system's real stages (3–6), go deep where the logic is (any depth), say what each node does in one line, show R/W effects with real names, and explain a node fully in Details.

**Spec:** `docs/specs/2026-10-18-codemap-v2.1-shape-and-depth.md` (overrides `2026-10-17-codemap-v2-design.md` where they conflict).

**Architecture:** Same layers. New: two-pass walk (`walk.py` skeleton + deepen), recursive split, `pipeline/explain.py` (node details), store migration 0002, UI N-level graph with measured cards and a two-tab right panel.

## Global Constraints

- `EffectOp = Literal["read", "write"]`. Mapping of old ops: write, delete, publish → write; read, consume, call → read.
- `Node.summary: str` — max 14 words. `Node.title` — max 4 words, never equal to an anchor symbol.
- Phases: max 7 (target 3–6). Plumbing (auth, validation, idempotency, dedupe, outbox relay, workflow/job runner, run bookkeeping, status updates) is never a phase.
- Eager split depth: 3 levels (0, 1, 2). Deeper levels on demand via expand. A node is expandable when its sub-path has ≥ 3 points.
- Walk budgets: skeleton 40 hops; deepen total 160 hops, split across phases by anchored lines of code (min 5 per phase).
- Details: generated on first open, stored; every "How it works" bullet cites lines inside the node's anchors or recorded hops; failed cites are dropped. Sections: header, How it works, Input, Output, Data touched, Calls, Code. No Branches, no Watch out.
- All v2 rules stay: recall-first hops, verifier, grounding, no source text stored, thread-safe store, 127.0.0.1 only.
- Code style: small files, one concern each, standard idioms. Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Old DBs (schema 1) open and migrate: old effect ops become read/write; old nodes get `summary = ""` and still render.
2. A repo whose flow has no clear stages (single file script) still yields ≥ 1 phase, not an error.
3. A phase with 0 deepen budget left (limits hit) still shows its skeleton steps; status partial with reason.
4. Details model call fails → panel still shows code, calls, data touched, with Retry.
5. Expanding a level-2 node in an eager trace builds level 3 on demand.

---

### Task 1: Domain, store migration, effect normalisation

**Files:** `domain/models.py`, `domain/rules.py`, `store/migrations/0002_v21.sql`, `store/db.py` (SCHEMA_VERSION=2), `store/traces.py`, new `store/details.py`, `repo/effects.py` (new) · tests in `tests/unit/`.

**Interfaces (produces):**
- `EffectOp = Literal["read","write"]`; `normalize_op(raw: str) -> EffectOp` (mapping above) in `domain/rules.py`.
- `Node.summary: str = ""`.
- `NodeExplain(BaseModel)`: `steps: tuple[ExplainStep, ...]`, `input: IoSide`, `output: IoSide`; `ExplainStep(text: str, lines: tuple[int, int], file: str)`; `IoSide(type: str, fields: tuple[str, ...], node_id: str | None)`.
- `normalize_target(category, raw) -> str` in `repo/effects.py`: strips "row", "rows", "table", "via …", quotes, trailing punctuation; S3 → `bucket/prefix` or `prefix/`; keeps real identifiers.
- Migration 0002: rewrite `effects` JSON ops in `nodes` and `walk_effects` with `normalize_op`; add `summary` handling (JSON-only model field, so Node rows: add column `summary TEXT NOT NULL DEFAULT ''`); create `node_details(trace_id, node_id, explain JSON, created_at, PRIMARY KEY(trace_id,node_id))`. The op rewrite runs in Python after the SQL file (migration hook `0002_v21.py` or a `post` function in db.py — builder's choice, tested).
- `TraceStore.get_explain(trace_id, node_id) -> NodeExplain | None`, `save_explain(trace_id, node_id, explain)`.
- `TraceStore.get_graph(trace_id, depth)` works for any depth (already level-based; test depth 3).

- [ ] Tests first: `test_normalize_op_mapping` (all six old ops), `test_normalize_target_cases` ("FileUpload row"→"FileUpload", "S3 via DocumentStorage.put"→kept meaningful? → returns "DocumentStorage" for object_store when no bucket/prefix given; "company_intelligence_document table"→"company_intelligence_document"), `test_migrate_v1_db_to_v2` (build a schema-1 DB with old ops, open, assert ops read/write and summary ""), `test_explain_roundtrip`, `test_graph_depth_3`.
- [ ] Implement; `make check`; commit `feat: v2.1 domain, migration, effect normalisation`.

### Task 2: Two-pass walk

**Files:** `pipeline/walk.py`, `prompts/walk_skeleton.md` (new), `prompts/walk_deepen.md` (new), remove/replace `prompts/walk.md` · tests `tests/pipeline/test_walk.py`.

**Interfaces:**
- `walk_skeleton(ctx, entry, question) -> WalkResult` — budget `settings.skeleton_hops` (40). Prompt: stage level only; follow handoffs (workflows, activities, queues) across processes; record the stage functions; do not descend into helpers; record effects at stage level.
- `walk_deepen(ctx, phase: Node, question, budget: int, known: list[Hop]) -> WalkResult` — starts from the phase's anchors; records hops only inside the phase's flow; prompt: go into the functions that do the real work (transform data, decide, compute), skip trivial helpers (validation one-liners, key builders, getters, logging); record every effect with real target names.
- `deepen_budgets(phases: list[Node], tools, total: int, floor: int = 5) -> dict[str, int]` — weight = anchored line count.
- `record_effect` applies `normalize_op` and `normalize_target`.
- Settings: `skeleton_hops: int = 40`, `deepen_hops: int = 160`.

- [ ] Tests first (ScriptedModel): skeleton stops at stage level (records ≤ budget); deepen only accepts hops whose caller is inside the phase subtree (others → error text to the agent); budgets weighted and floored; effect normalised on record.
- [ ] Implement; `make check`; commit.

### Task 3: Recursive split with summaries and stage rules

**Files:** `pipeline/split.py`, `prompts/split_phases.md`, `prompts/split_steps.md` · tests `tests/pipeline/test_split.py`.

**Interfaces:**
- Drafts gain `summary` (validator: ≤ 14 words). `title` validator: ≤ 4 words and not equal (case-insensitive) to any anchor symbol's last part.
- `PhasesSubmit` validator: 1–7 phases.
- `split_children(ctx, parent: Node, points: list[Anchor], effects) -> tuple[list[Node], str | None]` — generic: children of any node at `parent.level + 1`; replaces `split_steps`. Input = parent's anchored code inline (cap 800 lines, else outline + first 40 lines/anchor), sub-path points under it, no read tools, max_turns 4.
- `subpath_points(node: Node, hops) -> list[Anchor]` — path points whose anchors lie inside the node's anchors.
- Prompts: split_phases states the stage rule and plumbing list and the "orchestrator is edges" rule verbatim from spec §2.1; both prompts require title ≤ 4 words + summary ≤ 14 words.

- [ ] Tests first: a 10-point path with plumbing points → validator rejects 9 phases; title == symbol rejected; summary 20 words rejected; split_children at level 2 sets parent_id and level.
- [ ] Implement; `make check`; commit.

### Task 4: Orchestration for the new flow

**Files:** `pipeline/run.py`, `pipeline/validate.py` · tests `tests/pipeline/test_run.py`.

Flow: skeleton walk → points → split phases → save phases → for each phase (sequential): deepen walk with its budget → save hops → split children (level 1) → for each child with ≥ 3 sub-path points and level < 2: split children (level 2) → side nodes → validate (any depth; rollup recursive from leaves) → save → status.
- `expand_node(ctx, node_id)` replaces `expand_phase`: any level; runs `split_children` on that node (and a small deepen walk of 20 hops first if the node has < 3 sub-path points).
- Status partial reasons include deepen limits per phase.

- [ ] Tests first: end-to-end ScriptedModel run produces levels 0,1,2; recursive rollup; expand at level 2 builds level 3; old `expand_phase` callers updated (service/server).
- [ ] Implement; `make check`; commit.

### Task 5: Node details (explain)

**Files:** `pipeline/explain.py`, `prompts/explain.md`, `service.py` (`get_detail` returns `NodeDetail{explain: NodeExplain | None, explain_error: str | None, functions: FunctionDetail[], calls: [{symbol, node_id|None}], effects: Effect[]}`), `server/routes.py` + `schemas.py` · tests.

- `explain_node(ctx, node, hops, effects) -> NodeExplain` — one structured call (no tools, max_turns 3) with the node's full anchored code, parent/sibling titles, hops, effects. Grounding: drop steps whose `(file, lines)` are not inside the node's anchors or a recorded hop's caller range; input/output `node_id` must be an existing node id or null.
- Generated on first `get_detail`, stored via `save_explain`; later calls read it.
- `calls[].node_id` = the node whose anchors contain the callee anchor (deepest), so the UI can link.

- [ ] Tests first: grounding drops a bad cite; cached second call makes no model call; model error → `explain=None, explain_error=msg` and functions still returned.
- [ ] Implement; `make check`; commit.

### Task 6: UI — shape, cards, right panel

**Files:** `frontend/src/graph/visible.ts`, `graph/layout.ts`, `graph/measure.ts` (new), `canvas/NodeCard.tsx` (one card for all levels), `panels/RightPanel.tsx` (tabs), `panels/DetailsTab.tsx`, `panels/DataTab.tsx`, remove `effects/EffectLane.tsx` and the lane CSS, `effects/categories.ts` (R/W only), regenerate `api/schema.d.ts` · tests vitest + Playwright.

- Visible graph supports any depth: a node is visible when all its ancestors are open; edges reroute to the deepest visible ancestor.
- Card: title (bold) + summary (dim, wraps) + ≤ 2 chips (`R`/`W` + target) + `+N`; caret when it has children or is expandable. No input/output on cards.
- `measure.ts`: measure each card's height offscreen with the real CSS (fixed width per level: 220/190/170), cache by node id + text; layout uses measured sizes. Nothing clips (Playwright asserts `scrollHeight <= clientHeight` on every card).
- Right panel (resizable, 420px default), tabs **Details** and **Data touched**:
  - Details: header (title, summary, code name), How it works (numbered, cite links `file:line` that scroll the code view and highlight), Input / Output (type, fields, from/to node links that move the camera), Data touched (R/W, target, fields, line), Calls (links when `node_id`), Code (full, line numbers, cited lines highlighted). Loading state while explain runs; error + Retry.
  - Data touched: targets grouped by category; each row = target name + per-phase `R`/`W` tags; click highlights nodes that touch it, others fade.
- Design: follow the approved mockups (`v2.html`, `details.html` in the brainstorm content dir). Keep it clean.

- [ ] Tests first; implement; vitest + Playwright (real-server spec updated for 3 levels and the panel); commit.

### Task 7: Evals and real run

**Files:** `evals/codemap-trace.expected.json` (restructure to Start trace / Find entry / Walk & verify / Build levels / Validate & save; Build levels → Order path points, Split into phases, Expand each phase, Split into steps; deeper as in the summary md), `evals/score.py` (N-level: step agreement averaged over all matched parents; add `max_phases_ok`, `title_len_ok`, `summary_ok`), docs/notes/eval-results.md.

- [ ] Update expected + scorer with tests; controller then runs the real self-trace and the visual check with the user.
