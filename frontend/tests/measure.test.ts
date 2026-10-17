import { describe, expect, it, vi } from "vitest";
import { createSizer } from "../src/graph/measure";
import { buildVisible } from "../src/graph/visible";
import type { TraceGraph } from "../src/api/types";
import { node } from "./helpers";

const g = (title = "T"): TraceGraph => ({
  trace: {} as TraceGraph["trace"],
  nodes: [{ ...node("P", 0, null, 0), title, summary: "s" }, node("q", 1, "P", 0)],
  edges: [],
});

describe("sizer", () => {
  it("measures each card once per content and uses the fixed width per level", () => {
    const measure = vi.fn(() => 80);
    const sizer = createSizer(measure);
    const v = buildVisible(g(), new Set(["P"]));
    const p = v.nodes[0]!;
    const q = v.nodes[1]!;
    expect(sizer.header(p)).toBe(80);
    expect(sizer.card(q)).toEqual({ width: 190, height: 80 });
    sizer.card(q);
    sizer.header(p);
    expect(measure).toHaveBeenCalledTimes(2);
    expect(sizer.card(buildVisible(g(), new Set()).nodes[0]!)).toMatchObject({ width: 220 });
  });

  it("uses width 170 from level 2 down", () => {
    const sizer = createSizer(() => 50);
    const deep = buildVisible(
      { trace: {} as TraceGraph["trace"], nodes: [node("P", 0, null, 0), node("a", 1, "P", 0), node("b", 2, "a", 0), node("c", 3, "b", 0)], edges: [] },
      new Set(["P", "a", "b"]),
    );
    expect(deep.nodes.map((n) => sizer.card(n).width)).toEqual([220, 190, 170, 170]);
  });

  it("measures again when the text changes", () => {
    const measure = vi.fn(() => 60);
    const sizer = createSizer(measure);
    sizer.card(buildVisible(g("One"), new Set()).nodes[0]!);
    sizer.card(buildVisible(g("One two three"), new Set()).nodes[0]!);
    expect(measure).toHaveBeenCalledTimes(2);
  });
});
