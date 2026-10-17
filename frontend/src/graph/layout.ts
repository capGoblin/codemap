import type { ELK, ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";
import { cardWidth, FRAME_MIN_WIDTH, FRAME_PAD, type Sizer } from "./measure";
import type { VisibleEdge, VisibleNode } from "./visible";

export type Box = { x: number; y: number; width: number; height: number };
type V = { nodes: VisibleNode[]; edges: VisibleEdge[] };

// Sizes used when the caller gives no measurer (tests, first paint fallbacks).
export const estimateSizer: Sizer = {
  card: (vn) => ({ width: cardWidth(vn.depth), height: 96 }),
  header: () => 64,
};

// Space between the frame's title block and its children.
const FRAME_GAP = 14;

// Steps of one parallel group must share a layer. We give every member the
// union of the group's incoming sources, so layering cannot separate them.
function parallelEdges(v: V): ElkExtendedEdge[] {
  const groups = new Map<string, string[]>();
  for (const n of v.nodes) {
    const g = n.node.parallel_group;
    if (n.parentId === undefined || g === null) continue;
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

export function toElk(v: V, sizer: Sizer = estimateSizer): ElkNode {
  const els = new Map<string, ElkNode>();
  const roots: ElkNode[] = [];
  for (const n of v.nodes) {
    const el: ElkNode = { id: n.id };
    if (n.container) {
      el.children = [];
      el.layoutOptions = {
        "elk.padding": `[top=${sizer.header(n) + FRAME_GAP},left=${FRAME_PAD},bottom=${FRAME_PAD},right=${FRAME_PAD}]`,
        "elk.nodeSize.constraints": "[MINIMUM_SIZE]",
        "elk.nodeSize.minimum": `(${FRAME_MIN_WIDTH},0)`,
      };
    } else {
      Object.assign(el, sizer.card(n));
    }
    els.set(n.id, el);
    const parent = n.parentId === undefined ? undefined : els.get(n.parentId);
    (parent ? parent.children! : roots).push(el);
  }
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
      "elk.layered.spacing.nodeNodeBetweenLayers": "56",
      "elk.spacing.nodeNode": "28",
    },
    children: roots,
    edges,
  };
}

// Pure layout. Tests use the bundled ELK (node); the browser passes a worker-backed ELK.
export async function layout(
  v: V,
  elk?: Pick<ELK, "layout">,
  sizer: Sizer = estimateSizer,
): Promise<Map<string, Box>> {
  const engine = elk ?? new (await import("elkjs/lib/elk.bundled.js")).default();
  const out = new Map<string, Box>();
  const res = await engine.layout(toElk(v, sizer));
  const walk = (n: ElkNode) => {
    for (const c of n.children ?? []) {
      out.set(c.id, { x: c.x ?? 0, y: c.y ?? 0, width: c.width ?? 0, height: c.height ?? 0 });
      walk(c);
    }
  };
  walk(res);
  return out;
}
