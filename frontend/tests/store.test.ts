import { beforeEach, describe, expect, it } from "vitest";
import type { Edge, Node, TraceGraph } from "../src/api/types";
import { useStore } from "../src/state/store";
import { node } from "./helpers";

const g: TraceGraph = {
  trace: {} as TraceGraph["trace"],
  nodes: [
    node("P1", 0, null, 0), node("P2", 0, null, 1), node("s1", 1, "P1", 0),
  ] as Node[],
  edges: [] as Edge[],
};

describe("store", () => {
  beforeEach(() => {
    useStore.setState({
      graph: null, openIds: new Set(), selectedNodeId: null, selectedTarget: null,
      hiddenCategories: new Set(), focusNodeId: null, expandErrors: new Map(),
    });
    useStore.getState().setGraph(g);
  });

  it("toggleOpen opens, sets focus, and closes again", () => {
    useStore.getState().toggleOpen("P1");
    expect(useStore.getState().openIds.has("P1")).toBe(true);
    expect(useStore.getState().focusNodeId).toBe("P1");
    useStore.getState().toggleOpen("P1");
    expect(useStore.getState().openIds.has("P1")).toBe(false);
  });

  it("expandAll opens every phase and clears focus; collapseAll closes", () => {
    useStore.getState().toggleOpen("P1");
    useStore.getState().expandAll();
    expect([...useStore.getState().openIds].sort()).toEqual(["P1", "P2"]);
    expect(useStore.getState().focusNodeId).toBeNull();
    useStore.getState().collapseAll();
    expect(useStore.getState().openIds.size).toBe(0);
  });

  it("selection, category toggle, and expand errors", () => {
    const s = useStore.getState();
    s.selectNode("s1");
    s.selectTarget("db:users");
    s.toggleCategory("db");
    s.setExpandError("P1", "boom");
    expect(useStore.getState().selectedNodeId).toBe("s1");
    expect(useStore.getState().selectedTarget).toBe("db:users");
    expect(useStore.getState().hiddenCategories.has("db")).toBe(true);
    expect(useStore.getState().expandErrors.get("P1")).toBe("boom");
    s.toggleCategory("db");
    s.setExpandError("P1", null);
    expect(useStore.getState().hiddenCategories.has("db")).toBe(false);
    expect(useStore.getState().expandErrors.has("P1")).toBe(false);
  });
});
