import type { Effect, EdgeKind, Node, TraceGraph } from "../api/types";
import { chipsFor, type UiCategory } from "../effects/categories";

// Nodes below this level may still be split on demand.
export const MAX_EXPAND_LEVEL = 4;

export type VisibleNode = {
  id: string;
  depth: number;
  parentId?: string;
  open: boolean;
  // Open and showing its children: drawn as a frame around them.
  container: boolean;
  hasChildren: boolean;
  expandable: boolean;
  dimmed: boolean;
  chips: { shown: Effect[]; more: number };
  node: Node;
};
export type VisibleEdge = {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  dimmed: boolean;
};

const isSoft = (k: EdgeKind) => k === "error" || k === "branch";
const byOrder = (a: Node, b: Node) => a.order - b.order;

export function childrenOf(graph: TraceGraph): Map<string | null, Node[]> {
  const out = new Map<string | null, Node[]>();
  for (const n of graph.nodes) {
    const list = out.get(n.parent_id) ?? [];
    list.push(n);
    out.set(n.parent_id, list);
  }
  for (const list of out.values()) list.sort(byOrder);
  return out;
}

// A node is visible when all its ancestors are open. Edges to hidden nodes move to the
// deepest visible ancestor.
export function buildVisible(
  graph: TraceGraph,
  openIds: Set<string>,
  hidden: Set<UiCategory> = new Set(),
  leaves: Set<string> = new Set(),
): { nodes: VisibleNode[]; edges: VisibleEdge[] } {
  const kids = childrenOf(graph);
  const nodes: Omit<VisibleNode, "dimmed">[] = [];
  const visible = new Set<string>();

  const walk = (n: Node, depth: number, parentId?: string) => {
    const children = kids.get(n.id) ?? [];
    const open = openIds.has(n.id) && children.length > 0;
    visible.add(n.id);
    nodes.push({
      id: n.id,
      depth,
      ...(parentId !== undefined ? { parentId } : {}),
      open: openIds.has(n.id),
      container: open,
      hasChildren: children.length > 0,
      expandable: children.length > 0 || (n.anchors.length > 0 && n.level < MAX_EXPAND_LEVEL && !leaves.has(n.id)),
      chips: chipsFor(n.effects, hidden),
      node: n,
    });
    if (open) for (const c of children) walk(c, depth + 1, n.id);
  };
  for (const n of kids.get(null) ?? []) if (n.level === 0) walk(n, 0);

  const parent = new Map(graph.nodes.map((n) => [n.id, n.parent_id]));
  const lift = (id: string): string | undefined => {
    let cur: string | null | undefined = id;
    for (let i = 0; cur != null && i < 64; i++) {
      if (visible.has(cur)) return cur;
      cur = parent.get(cur);
    }
    return undefined;
  };

  const within = (id: string, anc: string): boolean => {
    let cur = parent.get(id);
    for (let i = 0; cur != null && i < 64; i++, cur = parent.get(cur)) if (cur === anc) return true;
    return false;
  };

  const edges: VisibleEdge[] = [];
  const seen = new Set<string>();
  for (const e of graph.edges) {
    const source = lift(e.source_id);
    const target = lift(e.target_id);
    if (!source || !target || source === target) continue;
    if (within(source, target) || within(target, source)) continue; // a frame to its own child
    const id = `${source}->${target}:${e.kind}`;
    if (seen.has(id)) continue;
    seen.add(id);
    edges.push({ id, source, target, kind: e.kind, dimmed: isSoft(e.kind) });
  }

  const incoming = new Map<string, VisibleEdge[]>();
  for (const e of edges) incoming.set(e.target, [...(incoming.get(e.target) ?? []), e]);
  return {
    nodes: nodes.map((n) => {
      const inc = incoming.get(n.id) ?? [];
      return { ...n, dimmed: inc.length > 0 && inc.every((e) => isSoft(e.kind)) };
    }),
    edges,
  };
}
