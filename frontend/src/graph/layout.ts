import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";
import type { VisibleEdge, VisibleNode } from "./visible";

export type Box = { x: number; y: number; width: number; height: number };
type V = { nodes: VisibleNode[]; edges: VisibleEdge[] };

const PHASE = { width: 220, height: 110 };
const STEP = { width: 180, height: 90 };

const elk = new ELK();

// Steps of one parallel group must share a layer. We give every member the
// union of the group's incoming sources, so layering cannot separate them.
function parallelEdges(v: V): ElkExtendedEdge[] {
  const groups = new Map<string, string[]>();
  for (const n of v.nodes) {
    const g = n.node.parallel_group;
    if (n.kind !== "step" || g === null) continue;
    const key = `${n.parentId}#${g}`;
    groups.set(key, [...(groups.get(key) ?? []), n.id]);
  }
  const extra: ElkExtendedEdge[] = [];
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const set = new Set(members);
    const sources = new Set(
      v.edges.filter((e) => set.has(e.target) && !set.has(e.source)).map((e) => e.source),
    );
    for (const m of members) {
      for (const s of sources) {
        if (v.edges.some((e) => e.source === s && e.target === m)) continue;
        extra.push({ id: `par:${s}->${m}`, sources: [s], targets: [m] });
      }
    }
  }
  return extra;
}

export function toElk(v: V): ElkNode {
  const children = new Map<string, ElkNode[]>();
  const roots: ElkNode[] = [];
  const phaseNode = new Map<string, ElkNode>();
  for (const n of v.nodes) {
    if (n.kind === "phase") {
      const el: ElkNode = { id: n.id };
      if (n.open) {
        el.children = [];
        el.layoutOptions = { "elk.padding": "[top=40,left=20,bottom=20,right=20]" };
      } else {
        Object.assign(el, PHASE);
      }
      phaseNode.set(n.id, el);
      roots.push(el);
    } else {
      const list = children.get(n.parentId!) ?? [];
      list.push({ id: n.id, ...STEP });
      children.set(n.parentId!, list);
    }
  }
  for (const [pid, list] of children) phaseNode.get(pid)!.children = list;
  const edges: ElkExtendedEdge[] = [
    ...v.edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
    ...parallelEdges(v),
  ];
  return {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.layered.spacing.nodeNodeBetweenLayers": "60",
    },
    children: roots,
    edges,
  };
}

export async function layout(v: V): Promise<Map<string, Box>> {
  const out = new Map<string, Box>();
  const res = await elk.layout(toElk(v));
  const walk = (n: ElkNode) => {
    for (const c of n.children ?? []) {
      out.set(c.id, { x: c.x ?? 0, y: c.y ?? 0, width: c.width ?? 0, height: c.height ?? 0 });
      walk(c);
    }
  };
  walk(res);
  return out;
}
