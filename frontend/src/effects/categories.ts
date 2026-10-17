import type { Anchor, Effect, EffectCategory, EffectOp, Node, TraceGraph } from "../api/types";

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
  external: "External call",
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

export function chipsFor(
  effects: Effect[],
  hidden: Set<UiCategory>,
): { shown: Effect[]; more: number } {
  const visible = effects.filter((e) => !hidden.has(uiCategory(e.category)));
  return { shown: visible.slice(0, 3), more: Math.max(0, visible.length - 3) };
}

export const targetKey = (e: Effect): string => `${uiCategory(e.category)}:${e.target}`;

export type Target = {
  key: string;
  label: string;
  uses: { nodeId: string; op: EffectOp; fields: string[]; anchor: Anchor }[];
};

const sig = (e: Effect): string =>
  `${targetKey(e)}|${e.op}|${e.anchor.file}:${e.anchor.start_line}-${e.anchor.end_line}`;

// Effects come from steps when a phase has steps. A phase also keeps its own effects that no
// step reports, because steps may cover only part of the phase.
function effectUses(graph: TraceGraph): { node: Node; effect: Effect }[] {
  const stepSigs = new Map<string, Set<string>>();
  for (const n of graph.nodes) {
    if (n.level > 0 && n.parent_id !== null) {
      const set = stepSigs.get(n.parent_id) ?? new Set<string>();
      n.effects.forEach((e) => set.add(sig(e)));
      stepSigs.set(n.parent_id, set);
    }
  }
  const out: { node: Node; effect: Effect }[] = [];
  for (const n of graph.nodes) {
    const covered = n.level === 0 ? stepSigs.get(n.id) : undefined;
    for (const effect of n.effects) {
      if (!covered?.has(sig(effect))) out.push({ node: n, effect });
    }
  }
  return out;
}

export function targetsOf(graph: TraceGraph, hidden: Set<UiCategory>): Map<UiCategory, Target[]> {
  const out = new Map<UiCategory, Target[]>();
  const byKey = new Map<string, Target>();
  for (const { node: n, effect: e } of effectUses(graph)) {
    const cat = uiCategory(e.category);
    if (hidden.has(cat)) continue;
    const key = targetKey(e);
    let t = byKey.get(key);
    if (!t) {
      t = { key, label: e.target, uses: [] };
      byKey.set(key, t);
      out.set(cat, [...(out.get(cat) ?? []), t]);
    }
    t.uses.push({ nodeId: n.id, op: e.op, fields: e.fields, anchor: e.anchor });
  }
  return out;
}

export function nodesTouching(graph: TraceGraph, key: string): Set<string> {
  const ids = new Set<string>();
  for (const { node: n, effect: e } of effectUses(graph)) {
    if (targetKey(e) !== key) continue;
    ids.add(n.id);
    if (n.parent_id !== null) ids.add(n.parent_id);
  }
  return ids;
}
