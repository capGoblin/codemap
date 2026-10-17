import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { FlowCanvas, type LayoutFn } from "../src/canvas/FlowCanvas";
import { Toolbar } from "../src/Toolbar";
import { useStore } from "../src/state/store";
import type { Effect, TraceGraph } from "../src/api/types";
import { fixtureGraph } from "../src/dev/fixture";
import { node } from "./helpers";

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

const fakeLayout: LayoutFn = async (v) =>
  new Map(
    v.nodes.map((n, i) => [n.id, { x: i * 10, y: i * 10, width: 200, height: 100 }] as const),
  );

const eff = (category: Effect["category"], target: string): Effect => ({
  category, target, op: "write", fields: [], anchor: fixtureGraph.nodes[0]!.anchors[0]!,
});

function setup(graph: TraceGraph, open: string[] = []) {
  useStore.setState({
    graph, openIds: new Set(open), selectedNodeId: null, selectedTarget: null,
    hiddenCategories: new Set(), focusNodeId: null, expandErrors: new Map(),
  });
  return render(
    <ReactFlowProvider>
      <Toolbar />
      <div style={{ width: 800, height: 600 }}>
        <FlowCanvas layoutFn={fakeLayout} />
      </div>
    </ReactFlowProvider>,
  );
}

const graphWith = (effects: Effect[], stale = false): TraceGraph => {
  const p = node("p", 0, null, 0);
  const q = node("q", 0, null, 1);
  p.effects = effects;
  p.stale = stale;
  return { ...fixtureGraph, nodes: [p, q], edges: [{ source_id: "p", target_id: "q", kind: "call" }] };
};

beforeEach(() => cleanup());
afterEach(() => cleanup());

describe("canvas", () => {
  it("clicking a phase toggles openIds", async () => {
    setup(graphWith([]));
    const el = await screen.findByTestId("node-p");
    fireEvent.click(el);
    expect(useStore.getState().openIds.has("p")).toBe(true);
    fireEvent.click(el);
    expect(useStore.getState().openIds.has("p")).toBe(false);
  });

  it("shows 3 chips and +2 for 5 effects", async () => {
    setup(graphWith(["a", "b", "c", "d", "e"].map((t) => eff("db", t))));
    await screen.findByTestId("node-p");
    expect(screen.getAllByTestId("chip")).toHaveLength(3);
    expect(screen.getByText("+2")).toBeTruthy();
  });

  it("hiding DB removes DB chips", async () => {
    setup(graphWith([eff("db", "users"), eff("cache", "c1")]));
    await screen.findByTestId("node-p");
    expect(screen.getAllByTestId("chip")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "DB" }));
    await waitFor(() => expect(screen.getAllByTestId("chip")).toHaveLength(1));
    expect(screen.getByTestId("chip").getAttribute("data-category")).toBe("cache");
  });

  it("stale node shows 'code changed'", async () => {
    setup(graphWith([], true));
    await screen.findByTestId("node-p");
    expect(screen.getAllByText("code changed")).toHaveLength(1);
  });

  it("selected target fades non-touching nodes", async () => {
    setup(graphWith([eff("db", "users")]));
    await screen.findByTestId("node-q");
    act(() => useStore.getState().selectTarget("db:users"));
    await waitFor(() =>
      expect(screen.getByTestId("node-q").style.opacity).toBe("0.3"),
    );
    expect(screen.getByTestId("node-p").style.opacity).toBe("1");
  });

  it("opens steps inside a phase", async () => {
    setup(fixtureGraph, ["p1"]);
    expect(await screen.findByTestId("node-p1.s1")).toBeTruthy();
  });
});
