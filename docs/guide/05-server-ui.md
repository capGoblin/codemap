# 05 — Server and UI

## HTTP API — `src/codemap/server/` (all under `/api/v1`, `127.0.0.1` only)

| Method + path | Does | Service call |
| --- | --- | --- |
| `GET /health` | version | — |
| `GET /traces` | list traces | `list_traces` |
| `GET /traces/{id}?depth=N` | nodes + edges down to depth N (UI asks all levels) | `get_graph` (refreshes `stale`) |
| `GET /traces/{id}/events?after=` | SSE: replays + streams `events` rows, ends after `finished` | `events` (polled 0.25 s) |
| `POST /traces/{id}/nodes/{node}/expand[?force=1]` | build children of any node; 409 if it has children and no force; 502 + reason on failure | `expand_node` |
| `GET /traces/{id}/nodes/{node}/detail` | `NodeDetail`; explain made on first call | `get_detail` |
| `POST .../detail/regenerate` | redo explain (Retry) | `regenerate_detail` |
| `GET /api/v1/openapi.json` | schema → TS types (`frontend/src/api/schema.d.ts`) | — |

Static: built UI from `server/static/`, SPA fallback, `index.html` no-cache.

## Frontend — `frontend/src/`

| Part | Files | Job |
| --- | --- | --- |
| Entry | `main.tsx`, `App.tsx` | route `/traces/:id` → load graph (all levels), live events; `/` → trace list |
| API | `api/client.ts`, `api/types.ts`, `api/useTraceEvents.ts` | typed fetch, SSE hook |
| State | `state/store.ts` (zustand), `state/expand.ts` | open nodes, selection, camera request (one-shot), filters, panel tab/width, expand in flight |
| Graph | `graph/visible.ts` | which nodes show (all ancestors open), edges rerouted to deepest visible ancestor, dimmed side paths |
| Size | `graph/measure.ts` | measure each card's real height offscreen (widths 220/190/170), cached → cards never clip |
| Layout | `graph/layout.ts`, `layout.browser.ts` | ELK layered, left→right, nested compound nodes; runs in ELK's own Web Worker |
| Canvas | `canvas/FlowCanvas.tsx`, `NodeCard.tsx`, `CardBody.tsx`, `edges.tsx` | React Flow; one card for every level (title, summary, ≤ 2 R/W chips, caret); async edges dashed |
| Panels | `panels/RightPanel.tsx`, `DetailsTab.tsx`, `DataTab.tsx`, `CodeView.tsx` | Details: how it works (cites → highlight code), input/output (links), data touched, calls (links), code. Data touched: targets by category, R/W per phase, click highlights nodes |
| Effects | `effects/categories.ts` | category labels/colours, chips, targets, which nodes touch a target |
| Chrome | `Toolbar.tsx`, `StatusBanner.tsx`, `ExpandErrors.tsx` | expand/collapse/fit, filters, panel toggle; running/partial/failed banner with reason; expand errors + Retry |

## UI flows

1. **Open trace**: load graph → `buildVisible` → measure → ELK → render → fit all.
2. **Open node**: toggle open → (no children? `POST expand`, spinner) → relayout → camera zooms onto the node.
3. **Expand all / Collapse all / Fit**: toolbar.
4. **Select node**: Details tab → `GET detail` (loading → explain) → click a cite → code scrolls + highlights; click input/output/call link → camera moves to that node.
5. **Data touched**: click a target row → its nodes glow, rest fade; click again clears.
6. **Live trace**: SSE `phase_split` / `finished` → refetch graph; open nodes and camera stay put.

## Dev

`make dev` → API on `127.0.0.1:8765` (`codemap serve-dev`) + Vite dev server with proxy. `make gen-api` regenerates TS types. Wheel build runs `npm ci && npm run build` (`hatch_build.py`; skip with `CODEMAP_SKIP_UI`).
