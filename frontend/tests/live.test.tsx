import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { FlowCanvas, type LayoutFn } from "../src/canvas/FlowCanvas";
import { ExpandErrors } from "../src/ExpandErrors";
import { StatusBanner } from "../src/StatusBanner";
import { useStore } from "../src/state/store";
import type { TraceGraph } from "../src/api/types";
import { fixtureGraph } from "../src/dev/fixture";
import { node } from "./helpers";

const expandNode = vi.fn();
vi.mock("../src/api/client", () => ({ expandNode: (...a: unknown[]) => expandNode(...a) }));

beforeAll(() => {
  class RO {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
  (globalThis as unknown as { DOMMatrixReadOnly: unknown }).DOMMatrixReadOnly ??= class {
    m22 = 1;
    constructor(public s?: string) {}
  };
});
afterEach(() => {
  cleanup();
  expandNode.mockReset();
});

const fakeLayout: LayoutFn = async (v) =>
  new Map(v.nodes.map((n, i) => [n.id, { x: i * 10, y: i * 10, width: 200, height: 100 }] as const));

function lazyGraph(): TraceGraph {
  return {
    ...fixtureGraph,
    trace: { ...fixtureGraph.trace, mode: "lazy" },
    nodes: [node("p", 0, null, 0), node("q", 0, null, 1)],
    edges: [],
  };
}

function setup(graph: TraceGraph) {
  useStore.setState({
    graph, openIds: new Set(), selectedNodeId: null, selectedTarget: null,
    hiddenCategories: new Set(), cameraRequest: null, expandErrors: new Map(), expanding: new Set(),
    leaves: new Set(), panelOpen: true, panelTab: "details",
  });
  return render(
    <ReactFlowProvider>
      <ExpandErrors />
      <div style={{ width: 800, height: 600 }}>
        <FlowCanvas layoutFn={fakeLayout} />
      </div>
    </ReactFlowProvider>,
  );
}

describe("StatusBanner", () => {
  it("shows status and last warning for a partial trace", () => {
    render(<StatusBanner status="partial" message="x" warning="model gave up on p2" />);
    expect(screen.getByTestId("status-banner").textContent).toContain("partial");
    expect(screen.getByTestId("status-banner").textContent).toContain("model gave up on p2");
  });
  it("shows the finished reason before the last warning", () => {
    render(<StatusBanner status="failed" message="x" warning="dropped L1 s" reason="walk: model error: 401" />);
    const text = screen.getByTestId("status-banner").textContent;
    expect(text).toContain("walk: model error: 401");
    expect(text).not.toContain("dropped L1 s");
  });
  it("shows the latest message while running and nothing when complete", () => {
    const { container, rerender } = render(<StatusBanner status="running" message="walking" warning={null} />);
    expect(screen.getByTestId("progress-strip").textContent).toBe("walking");
    rerender(<StatusBanner status="complete" message="x" warning={null} />);
    expect(container.textContent).toBe("");
  });
});

describe("lazy expand", () => {
  it("shows Retry on failure and merges children on retry", async () => {
    setup(lazyGraph());
    expandNode.mockRejectedValueOnce(new Error("build failed"));
    fireEvent.click(await screen.findByTestId("node-p"));
    expect(await screen.findByText(/build failed/)).toBeTruthy();
    expect(expandNode).toHaveBeenCalledWith("fixture", "p");

    const merged: TraceGraph = { ...lazyGraph(), nodes: [...lazyGraph().nodes, node("p.s1", 1, "p", 0)] };
    expandNode.mockResolvedValueOnce(merged);
    fireEvent.click(screen.getByText("Retry"));
    expect(await screen.findByTestId("node-p.s1")).toBeTruthy();
    expect(useStore.getState().expandErrors.size).toBe(0);
  });
});

describe("setGraph", () => {
  it("keeps open phases that still exist and drops the others", () => {
    useStore.setState({ openIds: new Set(["p", "gone"]), cameraRequest: null });
    act(() => useStore.getState().setGraph(lazyGraph()));
    expect([...useStore.getState().openIds]).toEqual(["p"]);
    expect(useStore.getState().cameraRequest).toBeNull();
  });
});

describe("expand any node", () => {
  it("a step with no children asks the server and shows the new level", async () => {
    const base = { ...fixtureGraph, nodes: [node("p", 0, null, 0), node("p.s1", 1, "p", 0)], edges: [] };
    setup(base);
    useStore.setState({ openIds: new Set(["p"]) });
    expandNode.mockResolvedValueOnce({ ...base, nodes: [...base.nodes, node("p.s1.a", 2, "p.s1", 0)] });
    fireEvent.click(await screen.findByTestId("node-p.s1"));
    expect(expandNode).toHaveBeenCalledWith("fixture", "p.s1");
    expect(await screen.findByTestId("node-p.s1.a")).toBeTruthy();
  });

  it("a node the server cannot split becomes a leaf with no caret", async () => {
    const base = { ...fixtureGraph, nodes: [node("p", 0, null, 0)], edges: [] };
    setup(base);
    expandNode.mockResolvedValueOnce(base);
    fireEvent.click(await screen.findByTestId("node-p"));
    await waitFor(() => expect(useStore.getState().leaves.has("p")).toBe(true));
    await waitFor(() => expect(screen.getByTestId("node-p").textContent).not.toContain("▸"));
    expect(useStore.getState().openIds.has("p")).toBe(false);
  });

  it("an eager phase with a failed split shows the error and retries", async () => {
    const p = { ...node("p", 0, null, 0), warnings: ["steps unavailable: rate limited"] };
    const base = { ...fixtureGraph, trace: { ...fixtureGraph.trace, mode: "eager" as const }, nodes: [p], edges: [] };
    setup(base);
    expandNode.mockRejectedValueOnce(new Error("rate limited"));
    fireEvent.click(await screen.findByTestId("node-p"));
    expect(await screen.findByText(/rate limited/)).toBeTruthy();
    expandNode.mockResolvedValueOnce({ ...base, nodes: [p, node("p.s1", 1, "p", 0)] });
    fireEvent.click(screen.getByText("Retry"));
    expect(await screen.findByTestId("node-p.s1")).toBeTruthy();
  });
});
