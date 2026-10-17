import type { EdgeKind, Node, TraceGraph } from "../api/types";

export type VisibleNode = {
  id: string;
  kind: "phase" | "step";
  parentId?: string;
  open: boolean;
  dimmed: boolean;
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

export function buildVisible(
  graph: TraceGraph,
  openIds: Set<string>,
): { nodes: VisibleNode[]; edges: VisibleEdge[] } {
  const byOrder = (a: Node, b: Node) => a.order - b.order;
  const phases = graph.nodes.filter((n) => n.level === 0).sort(byOrder);
  const stepsOf = new Map<string, Node[]>();
  for (const n of graph.nodes) {
    if (n.level === 0 || n.parent_id === null) continue;
    const list = stepsOf.get(n.parent_id) ?? [];
    list.push(n);
    stepsOf.set(n.parent_id, list);
  }

  const raw: { node: Node; kind: "phase" | "step"; parentId?: string; open: boolean }[] = [];
  const visibleIds = new Set<string>();
  const redirect = new Map<string, string>();
  for (const p of phases) {
    const open = openIds.has(p.id);
    raw.push({ node: p, kind: "phase", open });
    visibleIds.add(p.id);
    for (const s of (stepsOf.get(p.id) ?? []).sort(byOrder)) {
      if (open) {
        raw.push({ node: s, kind: "step", parentId: p.id, open: false });
        visibleIds.add(s.id);
      } else {
        redirect.set(s.id, p.id);
      }
    }
  }

  const edges: VisibleEdge[] = [];
  const seen = new Set<string>();
  for (const e of graph.edges) {
    const source = redirect.get(e.source_id) ?? e.source_id;
    const target = redirect.get(e.target_id) ?? e.target_id;
    if (source === target) continue;
    if (!visibleIds.has(source) || !visibleIds.has(target)) continue;
    const id = `${source}->${target}:${e.kind}`;
    if (seen.has(id)) continue;
    seen.add(id);
    edges.push({ id, source, target, kind: e.kind, dimmed: isSoft(e.kind) });
  }

  const incoming = new Map<string, VisibleEdge[]>();
  for (const e of edges) {
    const list = incoming.get(e.target) ?? [];
    list.push(e);
    incoming.set(e.target, list);
  }
  const nodes = raw.map((r) => {
    const inc = incoming.get(r.node.id) ?? [];
    return {
      id: r.node.id,
      kind: r.kind,
      ...(r.parentId !== undefined ? { parentId: r.parentId } : {}),
      open: r.open,
      dimmed: inc.length > 0 && inc.every((e) => isSoft(e.kind)),
      node: r.node,
    };
  });
  return { nodes, edges };
}
