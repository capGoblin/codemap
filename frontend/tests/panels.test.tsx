import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useStore } from "../src/state/store";
import { fixtureGraph } from "../src/dev/fixture";
import { DetailPanel } from "../src/panels/DetailPanel";
import { EffectPanel } from "../src/panels/EffectPanel";
import { EffectLane } from "../src/effects/EffectLane";
import type { DetailLoader } from "../src/api/types";

beforeEach(() => {
  useStore.setState({
    graph: fixtureGraph, openIds: new Set(), selectedNodeId: null, selectedTarget: null,
    hiddenCategories: new Set(), cameraRequest: null, expandErrors: new Map(),
  });
});
afterEach(cleanup);

const anchor = { file: "app/x.py", start_line: 40, end_line: 42, symbol: "f", content_hash: "h" };
const loader: DetailLoader = vi.fn(async () => ({
  explain: null,
  explain_error: null,
  calls: [],
  effects: [],
  functions: [
    { anchor, signature: "def f(a)", code: "line one\nline two\nline three", calls: ["g", "h"] },
  ],
}));

describe("DetailPanel", () => {
  it("shows code with line numbers from start_line, calls and node info", async () => {
    useStore.setState({ selectedNodeId: "p2.s2" });
    render(<DetailPanel loader={loader} />);
    expect(loader).toHaveBeenCalledWith("fixture", "p2.s2");
    expect(await screen.findByText("line two")).toBeTruthy();
    expect(screen.getByText("41")).toBeTruthy();
    expect(screen.getByText("def f(a)")).toBeTruthy();
    expect(screen.getByText("g")).toBeTruthy();
    expect(screen.getByText("Code changed since this trace; snippet may not match.")).toBeTruthy();
  });

  it("is hidden without selection and close clears it", async () => {
    const { container } = render(<DetailPanel loader={loader} />);
    expect(container.innerHTML).toBe("");
    cleanup();
    useStore.setState({ selectedNodeId: "p1.s1" });
    render(<DetailPanel loader={loader} />);
    expect(screen.queryByText(/Code changed/)).toBeNull();
    fireEvent.click(screen.getByLabelText("Close detail"));
    expect(useStore.getState().selectedNodeId).toBeNull();
  });

  it("shows an error when loading fails", async () => {
    useStore.setState({ selectedNodeId: "p1.s1" });
    render(<DetailPanel loader={async () => { throw new Error("boom"); }} />);
    await waitFor(() => expect(screen.getByText(/boom/)).toBeTruthy());
  });
});

describe("EffectLane", () => {
  it("renders one column per visible category and selects a target", () => {
    useStore.setState({ hiddenCategories: new Set(["file"]) });
    render(<EffectLane />);
    expect(screen.getByText("DB")).toBeTruthy();
    expect(screen.getByText("Cache")).toBeTruthy();
    expect(screen.queryByText("File")).toBeNull();
    fireEvent.click(screen.getByTestId("target-db:orders"));
    expect(useStore.getState().selectedTarget).toBe("db:orders");
  });

  it("collapses", () => {
    render(<EffectLane />);
    fireEvent.click(screen.getByLabelText("Toggle effect lane"));
    expect(screen.queryByTestId("target-db:orders")).toBeNull();
  });
});

describe("EffectPanel", () => {
  it("lists uses and a row click opens the parent phase and requests focus", () => {
    useStore.setState({ selectedTarget: "db:orders" });
    render(<EffectPanel />);
    const row = screen.getByTestId("use-p2.s2");
    expect(row.textContent).toContain("W");
    expect(row.textContent).toContain("Save order");
    expect(row.textContent).toContain("app/service.py:1");
    fireEvent.click(row);
    const s = useStore.getState();
    expect(s.openIds.has("p2")).toBe(true);
    expect(s.cameraRequest).toEqual({ kind: "focus", id: "p2.s2" });
  });

  it("hidden without a target", () => {
    const { container } = render(<EffectPanel />);
    expect(container.innerHTML).toBe("");
  });
});
