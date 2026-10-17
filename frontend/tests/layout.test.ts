import { describe, expect, it } from "vitest";
import type { Edge, Node, TraceGraph } from "../src/api/types";
import { buildVisible } from "../src/graph/visible";
import { layout } from "../src/graph/layout";
import { node } from "./helpers";

const mk = (nodes: Node[], edges: Edge[]) =>
  ({ trace: {} as TraceGraph["trace"], nodes, edges }) as TraceGraph;

describe("layout", () => {
  const g = mk(
    [
      node("P1", 0, null, 0), node("P2", 0, null, 1),
      node("s1", 1, "P1", 0), node("s2", 1, "P1", 1),
    ],
    [
      { source_id: "P1", target_id: "P2", kind: "call" },
      { source_id: "s1", target_id: "s2", kind: "call" },
    ],
  );

  it("places P2 right of P1 and grows P1 when opened", async () => {
    const closed = await layout(buildVisible(g, new Set()));
    expect(closed.get("P2")!.x).toBeGreaterThan(closed.get("P1")!.x);
    expect(closed.get("P1")).toMatchObject({ width: 220, height: 110 });
    const open = await layout(buildVisible(g, new Set(["P1"])));
    expect(open.get("P1")!.width).toBeGreaterThan(220);
    expect(open.get("P2")!.x).toBeGreaterThan(closed.get("P2")!.x);
    expect(open.get("s1")).toMatchObject({ width: 180, height: 90 });
    expect(open.get("s2")!.x).toBeGreaterThan(open.get("s1")!.x);
  });

  it("gives an open phase without steps the closed size", async () => {
    const e = mk([node("P1", 0, null, 0)], []);
    const r = await layout(buildVisible(e, new Set(["P1"])));
    expect(r.get("P1")).toMatchObject({ width: 220, height: 110 });
  });

  it("puts parallel steps in the same layer", async () => {
    const pg = (n: Node, group: number | null): Node => ({ ...n, parallel_group: group });
    const p = mk(
      [
        node("P1", 0, null, 0),
        node("a", 1, "P1", 0), pg(node("b", 1, "P1", 1), 1), pg(node("c", 1, "P1", 2), 1),
        node("d", 1, "P1", 3),
      ],
      [
        { source_id: "a", target_id: "b", kind: "call" },
        { source_id: "b", target_id: "d", kind: "call" },
        { source_id: "c", target_id: "d", kind: "call" },
      ],
    );
    const r = await layout(buildVisible(p, new Set(["P1"])));
    expect(r.get("c")!.x).toBe(r.get("b")!.x);
    expect(r.get("c")!.y).not.toBe(r.get("b")!.y);
  });

  it("lays out 40 phases x 8 steps, all open, in under 2000 ms", async () => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    for (let p = 0; p < 40; p++) {
      nodes.push(node(`P${p}`, 0, null, p));
      if (p > 0) edges.push({ source_id: `P${p - 1}`, target_id: `P${p}`, kind: "call" });
      for (let s = 0; s < 8; s++) {
        nodes.push(node(`P${p}.s${s}`, 1, `P${p}`, s));
        if (s > 0) edges.push({ source_id: `P${p}.s${s - 1}`, target_id: `P${p}.s${s}`, kind: "call" });
      }
    }
    const open = new Set(nodes.filter((n) => n.level === 0).map((n) => n.id));
    const v = buildVisible(mk(nodes, edges), open);
    const t0 = performance.now();
    const r = await layout(v);
    const ms = performance.now() - t0;
    console.log(`layout 40x8 took ${ms.toFixed(0)} ms`);
    expect(r.size).toBe(360);
    expect(ms).toBeLessThan(2000);
  });
});
