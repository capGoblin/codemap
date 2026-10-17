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
      hiddenCategories: new Set(), cameraRequest: null, expandErrors: new Map(),
    });
    useStore.getState().setGraph(g);
  });

  it("toggleOpen opens, sets focus, and closes again", () => {
    useStore.getState().toggleOpen("P1");
    expect(useStore.getState().openIds.has("P1")).toBe(true);
    expect(useStore.getState().cameraRequest).toEqual({ kind: "focus", id: "P1" });
    useStore.getState().toggleOpen("P1");
    expect(useStore.getState().openIds.has("P1")).toBe(false);
  });

  it("expandAll opens every node that has children and requests fit-all; collapseAll closes", () => {
    useStore.getState().toggleOpen("P1");
    useStore.getState().expandAll();
    expect([...useStore.getState().openIds]).toEqual(["P1"]);
    expect(useStore.getState().cameraRequest).toEqual({ kind: "all" });
    useStore.getState().collapseAll();
    expect(useStore.getState().openIds.size).toBe(0);
  });

  it("takeCameraRequest returns the request once and clears it", () => {
    useStore.getState().expandAll();
    expect(useStore.getState().takeCameraRequest()).toEqual({ kind: "all" });
    expect(useStore.getState().takeCameraRequest()).toBeNull();
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

describe("focusNode", () => {
  beforeEach(() => useStore.setState({ graph: g, openIds: new Set(), cameraRequest: null }));
  it("opens the parent phase of a step and requests focus", () => {
    useStore.getState().focusNode("s1");
    expect([...useStore.getState().openIds]).toEqual(["P1"]);
    expect(useStore.getState().cameraRequest).toEqual({ kind: "focus", id: "s1" });
  });
  it("opens every ancestor of a deep node", () => {
    const deep = { ...g, nodes: [...g.nodes, node("d", 2, "s1", 0), node("e", 3, "d", 0)] };
    useStore.setState({ graph: deep });
    useStore.getState().focusNode("e");
    expect([...useStore.getState().openIds].sort()).toEqual(["P1", "d", "s1"]);
  });
  it("only requests focus for a phase", () => {
    useStore.getState().focusNode("P2");
    expect(useStore.getState().openIds.size).toBe(0);
    expect(useStore.getState().cameraRequest).toEqual({ kind: "focus", id: "P2" });
  });
});

describe("panel", () => {
  it("selecting a node shows Details; tabs and width are clamped", () => {
    useStore.setState({ panelOpen: false, panelTab: "data" });
    useStore.getState().selectNode("s1");
    expect(useStore.getState()).toMatchObject({ panelOpen: true, panelTab: "details" });
    useStore.getState().showPanel("data");
    expect(useStore.getState().panelTab).toBe("data");
    useStore.getState().setPanelWidth(10);
    expect(useStore.getState().panelWidth).toBe(320);
  });
  it("markLeaf closes the node and remembers it", () => {
    useStore.setState({ openIds: new Set(["P2"]), leaves: new Set() });
    useStore.getState().markLeaf("P2");
    expect(useStore.getState().openIds.has("P2")).toBe(false);
    expect(useStore.getState().leaves.has("P2")).toBe(true);
  });
});
