import { describe, expect, it } from "vitest";
import type { Edge, Node, TraceGraph } from "../src/api/types";
import { node } from "./helpers";
import { buildVisible } from "../src/graph/visible";

function graph(nodes: Node[], edges: Edge[]): TraceGraph {
  return { trace: {} as TraceGraph["trace"], nodes, edges };
}

// P1 -> s1, s2 ; s1 -> a, b (level 2) ; b -> c (level 3)
const g = graph(
  [
    node("P1", 0, null, 0), node("P2", 0, null, 1),
    node("s1", 1, "P1", 0), node("s2", 1, "P1", 1),
    node("a", 2, "s1", 0), node("b", 2, "s1", 1), node("c", 3, "b", 0),
  ],
  [
    { source_id: "P1", target_id: "P2", kind: "call" },
    { source_id: "s1", target_id: "s2", kind: "call" },
    { source_id: "s1", target_id: "P2", kind: "call" },
    { source_id: "s2", target_id: "P2", kind: "error" },
    { source_id: "a", target_id: "b", kind: "call" },
    { source_id: "b", target_id: "s2", kind: "async" },
  ],
);

describe("buildVisible", () => {
  it("hides everything below a closed node and reroutes edges once", () => {
    const v = buildVisible(g, new Set());
    expect(v.nodes.map((n) => n.id)).toEqual(["P1", "P2"]);
    const p1p2 = v.edges.filter((e) => e.source === "P1" && e.target === "P2" && e.kind === "call");
    expect(p1p2).toHaveLength(1);
    expect(v.edges.some((e) => e.source === "s1" || e.target === "s1")).toBe(false);
    expect(v.edges.some((e) => e.source === e.target)).toBe(false);
  });

  it("shows children after their parent, in pre-order, with depth and parentId", () => {
    const v = buildVisible(g, new Set(["P1", "s1"]));
    expect(v.nodes.map((n) => n.id)).toEqual(["P1", "s1", "a", "b", "s2", "P2"]);
    expect(v.nodes.find((n) => n.id === "a")).toMatchObject({ depth: 2, parentId: "s1" });
    expect(v.nodes.find((n) => n.id === "P1")).toMatchObject({ open: true, container: true });
    expect(v.edges.some((e) => e.source === "a" && e.target === "b")).toBe(true);
  });

  it("an open node is visible only when all its ancestors are open", () => {
    const v = buildVisible(g, new Set(["s1", "b"])); // P1 closed
    expect(v.nodes.map((n) => n.id)).toEqual(["P1", "P2"]);
  });

  it("moves edges to the deepest visible ancestor at any depth", () => {
    const v = buildVisible(g, new Set(["P1", "s1"]));
    // b -> s2 stays between two visible siblings of different depth
    expect(v.edges.some((e) => e.source === "b" && e.target === "s2" && e.kind === "async")).toBe(true);
    // c is hidden under closed b; an edge to c would land on b
    const g2 = graph(g.nodes, [...g.edges, { source_id: "s2", target_id: "c", kind: "call" }]);
    const v2 = buildVisible(g2, new Set(["P1", "s1"]));
    expect(v2.edges.some((e) => e.source === "s2" && e.target === "b" && e.kind === "call")).toBe(true);
  });

  it("drops an edge between a frame and its own descendant", () => {
    const g3 = graph(g.nodes, [{ source_id: "P1", target_id: "s1", kind: "call" }]);
    expect(buildVisible(g3, new Set(["P1"])).edges).toEqual([]);
  });

  it("marks expandable nodes: children, or an anchor below level 4, unless a known leaf", () => {
    const v = buildVisible(g, new Set(["P1"]), new Set(), new Set(["s2"]));
    const by = (id: string) => v.nodes.find((n) => n.id === id)!;
    expect(by("P1")).toMatchObject({ hasChildren: true, expandable: true });
    expect(by("s1").expandable).toBe(true);
    expect(by("s2").expandable).toBe(false); // known leaf
    const deep = graph([node("P", 0, null, 0), { ...node("x", 4, "P", 0) }], []);
    expect(buildVisible(deep, new Set(["P"])).nodes.find((n) => n.id === "x")!.expandable).toBe(false);
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
  });
});
