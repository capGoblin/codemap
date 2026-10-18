import type { Effect, EffectCategory, EffectOp, Node, TraceGraph } from "../api/types";

export type UiCategory =
  | "db" | "object_store" | "queue_workflow" | "cache" | "file" | "external";

export function uiCategory(c: EffectCategory): UiCategory {
  switch (c) {
    case "queue":
    case "workflow":
      return "queue_workflow";
    case "http":
    case "other":
      return "external";
    default:
      return c;
  }
}

export const CATEGORY_LABEL: Record<UiCategory, string> = {
  db: "DB",
  object_store: "Object store",
  queue_workflow: "Queue / Workflow",
  cache: "Cache",
  file: "File",
  external: "External",
};

export const CATEGORY_COLOR: Record<UiCategory, string> = {
  db: "var(--cat-db)",
  object_store: "var(--cat-object-store)",
  queue_workflow: "var(--cat-queue-workflow)",
  cache: "var(--cat-cache)",
  file: "var(--cat-file)",
  external: "var(--cat-external)",
};

const OP_LETTER: Record<EffectOp, string> = {
  write: "W", read: "R",
};
export const opLetter = (op: EffectOp): string => OP_LETTER[op];

export const MAX_CHIPS = 2;

export function chipsFor(
  effects: Effect[],
  hidden: Set<UiCategory>,
): { shown: Effect[]; more: number } {
  const seen = new Set<string>();
  const visible = effects.filter((e) => {
    const k = `${e.op}:${targetKey(e)}`;
    if (hidden.has(uiCategory(e.category)) || seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return { shown: visible.slice(0, MAX_CHIPS), more: Math.max(0, visible.length - MAX_CHIPS) };
}

export const targetKey = (e: Effect): string => `${uiCategory(e.category)}:${e.target}`;

export type Target = {
  key: string;
  label: string;
  // One tag per (top-level phase, op): "W Save", "R Resolve".
  tags: { phaseId: string; phaseTitle: string; op: EffectOp }[];
};

function rootOf(graph: TraceGraph): (n: Node) => Node {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  return (n) => {
    let cur = n;
    for (let i = 0; cur.parent_id !== null && i < 64; i++) {
      const up = byId.get(cur.parent_id);
      if (!up) break;
      cur = up;
    }
    return cur;
  };
}

export function targetsOf(graph: TraceGraph, hidden: Set<UiCategory>): Map<UiCategory, Target[]> {
  const root = rootOf(graph);
  const phases = graph.nodes.filter((n) => n.level === 0).sort((a, b) => a.order - b.order);
  const out = new Map<UiCategory, Target[]>();
  const byKey = new Map<string, Target>();
  // Walk phases in order so the tags read in flow order.
  const rank = new Map(phases.map((p, i) => [p.id, i]));
  for (const n of graph.nodes) {
    const phase = root(n);
    for (const e of n.effects) {
      const cat = uiCategory(e.category);
      if (hidden.has(cat)) continue;
      const key = targetKey(e);
      let t = byKey.get(key);
      if (!t) {
        t = { key, label: e.target, tags: [] };
        byKey.set(key, t);
        out.set(cat, [...(out.get(cat) ?? []), t]);
      }
      if (!t.tags.some((x) => x.phaseId === phase.id && x.op === e.op)) {
        t.tags.push({ phaseId: phase.id, phaseTitle: phase.title, op: e.op });
      }
    }
  }
  for (const list of out.values()) {
    for (const t of list) {
      t.tags.sort((a, b) => (rank.get(a.phaseId) ?? 0) - (rank.get(b.phaseId) ?? 0));
    }
  }
  return out;
}

// Nodes that touch the target, plus their ancestors, so a closed phase lights up too.
export function nodesTouching(graph: TraceGraph, key: string): Set<string> {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const ids = new Set<string>();
  for (const n of graph.nodes) {
    if (!n.effects.some((e) => targetKey(e) === key)) continue;
    let cur: Node | undefined = n;
    while (cur && !ids.has(cur.id)) {
      ids.add(cur.id);
      cur = cur.parent_id === null ? undefined : byId.get(cur.parent_id);
    }
  }
  return ids;
}
