import { describe, expect, it } from "vitest";
import type { Edge, Node, TraceGraph } from "../src/api/types";
import { node } from "./helpers";
import { buildVisible } from "../src/graph/visible";

function graph(nodes: Node[], edges: Edge[]): TraceGraph {
  return { trace: {} as TraceGraph["trace"], nodes, edges };
}

const g = graph(
  [
    node("P1", 0, null, 0), node("P2", 0, null, 1),
    node("s1", 1, "P1", 0), node("s2", 1, "P1", 1),
  ],
  [
    { source_id: "P1", target_id: "P2", kind: "call" },
    { source_id: "s1", target_id: "s2", kind: "call" },
    { source_id: "s1", target_id: "P2", kind: "call" },
    { source_id: "s2", target_id: "P2", kind: "error" },
  ],
);

describe("buildVisible", () => {
  it("hides steps of closed phases and reroutes edges once", () => {
    const v = buildVisible(g, new Set());
    expect(v.nodes.map((n) => n.id)).toEqual(["P1", "P2"]);
    const p1p2 = v.edges.filter((e) => e.source === "P1" && e.target === "P2" && e.kind === "call");
    expect(p1p2).toHaveLength(1);
    expect(v.edges.some((e) => e.source === "s1" || e.target === "s1")).toBe(false);
    // s1->s2 collapses to a self loop on P1 and is dropped
    expect(v.edges.some((e) => e.source === e.target)).toBe(false);
  });

  it("shows steps after their parent when open", () => {
    const v = buildVisible(g, new Set(["P1"]));
    const ids = v.nodes.map((n) => n.id);
    expect(ids.indexOf("s1")).toBeGreaterThan(ids.indexOf("P1"));
    expect(ids.indexOf("s2")).toBeGreaterThan(ids.indexOf("P1"));
    expect(v.nodes.find((n) => n.id === "s1")).toMatchObject({ kind: "step", parentId: "P1" });
    expect(v.nodes.find((n) => n.id === "P1")).toMatchObject({ kind: "phase", open: true });
    expect(v.edges.some((e) => e.source === "s1" && e.target === "s2")).toBe(true);
  });

  it("dims error edges and nodes reached only by error/branch edges", () => {
    const e = graph(
      [node("P1", 0, null, 0), node("P2", 0, null, 1), node("P3", 0, null, 2)],
      [
        { source_id: "P1", target_id: "P2", kind: "call" },
        { source_id: "P1", target_id: "P3", kind: "error" },
      ],
    );
    const v = buildVisible(e, new Set());
    expect(v.edges.find((x) => x.target === "P3")!.dimmed).toBe(true);
    expect(v.edges.find((x) => x.target === "P2")!.dimmed).toBe(false);
    expect(v.nodes.find((n) => n.id === "P3")!.dimmed).toBe(true);
    expect(v.nodes.find((n) => n.id === "P2")!.dimmed).toBe(false);
    expect(v.nodes.find((n) => n.id === "P1")!.dimmed).toBe(false);
  });
});
