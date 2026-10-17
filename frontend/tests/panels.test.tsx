import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useStore } from "../src/state/store";
import { fixtureGraph } from "../src/dev/fixture";
import { DetailsTab } from "../src/panels/DetailsTab";
import { DataTab } from "../src/panels/DataTab";
import { RightPanel } from "../src/panels/RightPanel";
import type { DetailLoader, NodeDetail } from "../src/api/types";

beforeEach(() => {
  useStore.setState({
    graph: fixtureGraph, openIds: new Set(), selectedNodeId: null, selectedTarget: null,
    hiddenCategories: new Set(), cameraRequest: null, expandErrors: new Map(),
    panelOpen: true, panelTab: "details", panelWidth: 420, leaves: new Set(),
  });
});
afterEach(cleanup);

const anchor = { file: "app/x.py", start_line: 40, end_line: 44, symbol: "f", content_hash: "h" };
const detail: NodeDetail = {
  explain: {
    steps: [
      { text: "Reads the row.", file: "app/x.py", lines: [41, 42] },
      { text: "Saves it.", file: "app/x.py", lines: [44, 44] },
    ],
    input: { type: "Payment", fields: ["id"], node_id: "p2.s1" },
    output: { type: "str", fields: [], node_id: "p3" },
  },
  explain_error: null,
  functions: [
    { anchor, signature: "def f(a)", code: "def f(a):\n    x = 1\n    y = 2\n    z = 3\n    return z", calls: ["g"] },
  ],
  calls: [{ symbol: "g", node_id: "p3" }, { symbol: "h", node_id: null }],
  effects: [{ category: "db", target: "orders", op: "write", fields: ["status"], anchor: { ...anchor, start_line: 44, end_line: 44 } }],
};
const loader: DetailLoader = vi.fn(async () => detail);

function select(id = "p2.s2") {
  useStore.setState({ selectedNodeId: id });
}

describe("DetailsTab", () => {
  it("asks to select a node when none is selected", () => {
    render(<DetailsTab loader={loader} />);
    expect(screen.getByText(/Select a node/)).toBeTruthy();
  });

  it("shows header, steps, input/output, data touched, calls and code", async () => {
    select();
    render(<DetailsTab loader={loader} />);
    expect(loader).toHaveBeenCalledWith("fixture", "p2.s2");
    expect(screen.getByRole("heading", { name: "Save order" })).toBeTruthy();
    expect(screen.getByText(/app\/service.py:1 · p2\.s2|app\/service.py:1/)).toBeTruthy();
    expect(await screen.findByText("Reads the row.")).toBeTruthy();
    expect(screen.getByText("x.py:41–42")).toBeTruthy();
    expect(screen.getByTestId("io-input").textContent).toContain("Payment");
    expect(screen.getByTestId("io-input").textContent).toContain("from Charge card");
    expect(screen.getByTestId("io-output").textContent).toContain("to Notify");
    expect(screen.getByText("orders")).toBeTruthy();
    expect(screen.getByText("status")).toBeTruthy();
    expect(screen.getByText("h")).toBeTruthy();
    expect(screen.getByTestId("code-view").textContent).toContain("return z");
    expect(screen.getByText("Code changed since this trace; snippet may not match.")).toBeTruthy();
    expect(screen.queryByText("Branches")).toBeNull();
    expect(screen.queryByText("Watch out")).toBeNull();
  });

  it("shows a skeleton while loading", async () => {
    select();
    let done!: (d: NodeDetail) => void;
    const slow: DetailLoader = () => new Promise((r) => (done = r));
    render(<DetailsTab loader={slow} />);
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
    await act(async () => done(detail));
    expect(screen.queryByTestId("skeleton")).toBeNull();
  });

  it("clicking a cite highlights its lines in the code", async () => {
    select();
    render(<DetailsTab loader={loader} />);
    const cite = await screen.findByText("x.py:41–42");
    const lines = () => Array.from(screen.getByTestId("code-view").querySelectorAll(".code-line"));
    // Cited lines carry a light tint before any click.
    expect(lines().filter((l) => l.className.includes("hl")).map((l) => l.getAttribute("data-line"))).toEqual(["41", "42", "44"]);
    expect(lines().some((l) => l.className.includes("hl-active"))).toBe(false);
    fireEvent.click(cite);
    expect(lines().filter((l) => l.className.includes("hl-active")).map((l) => l.getAttribute("data-line"))).toEqual(["41", "42"]);
  });

  it("scrolls the code to the cited line", async () => {
    select();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    render(<DetailsTab loader={loader} />);
    fireEvent.click((await screen.findAllByText("x.py:44"))[0]!);
    // Two matches: the step cite and the effect row. Both point at line 44.
    expect(scroll).toHaveBeenCalled();
  });

  it("links to nodes move the camera and select", async () => {
    select();
    render(<DetailsTab loader={loader} />);
    fireEvent.click(await screen.findByText("Notify", { selector: ".io-from .link" }));
    const s = useStore.getState();
    expect(s.selectedNodeId).toBe("p3");
    expect(s.cameraRequest).toEqual({ kind: "focus", id: "p3" });
  });

  it("calls with a node_id are links; others are plain", async () => {
    select();
    render(<DetailsTab loader={loader} />);
    await screen.findByText("Reads the row.");
    const calls = screen.getByText("h").closest("ul")!;
    expect(calls.querySelectorAll("button.link")).toHaveLength(1);
    fireEvent.click(calls.querySelector("button.link")!);
    expect(useStore.getState().selectedNodeId).toBe("p3");
  });

  it("shows the error and Retry; Retry calls regenerate and shows the result", async () => {
    select();
    const failed = { ...detail, explain: null, explain_error: "model down" };
    const regen = vi.fn(async () => detail);
    render(<DetailsTab loader={async () => failed} regenerator={regen} />);
    expect(await screen.findByText(/model down/)).toBeTruthy();
    // Code, calls and data touched stay visible.
    expect(screen.getByTestId("code-view").textContent).toContain("return z");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(regen).toHaveBeenCalledWith("fixture", "p2.s2");
    expect(await screen.findByText("Reads the row.")).toBeTruthy();
    expect(screen.queryByText(/model down/)).toBeNull();
  });

  it("shows a load failure with Retry that loads again", async () => {
    select();
    const fn = vi.fn<DetailLoader>().mockRejectedValueOnce(new Error("boom")).mockResolvedValue(detail);
    render(<DetailsTab loader={fn} />);
    expect(await screen.findByText(/boom/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Reads the row.")).toBeTruthy();
    expect(fn).toHaveBeenCalledTimes(2);
  });
});

describe("DataTab", () => {
  it("groups targets by category with per-phase R/W tags", () => {
    render(<DataTab />);
    const db = screen.getByTestId("data-tab").querySelector('[data-category="db"]')!;
    expect(db.textContent).toContain("DB");
    const orders = screen.getByTestId("target-db:orders");
    expect(orders.textContent).toContain("orders");
    expect(orders.textContent).toContain("W Charge and store");
    expect(screen.getByTestId("target-db:users").textContent).toContain("R Validate request");
    expect(screen.getByTestId("target-queue_workflow:order-events").textContent).toContain("W Notify");
    expect(screen.getByText("External")).toBeTruthy();
  });

  it("clicking a row selects the target; clicking again clears it", () => {
    render(<DataTab />);
    fireEvent.click(screen.getByTestId("target-db:orders"));
    expect(useStore.getState().selectedTarget).toBe("db:orders");
    fireEvent.click(screen.getByTestId("target-db:orders"));
    expect(useStore.getState().selectedTarget).toBeNull();
  });

  it("omits hidden categories", () => {
    useStore.setState({ hiddenCategories: new Set(["file"]) });
    render(<DataTab />);
    expect(screen.queryByText("File")).toBeNull();
    expect(screen.getByText("Cache")).toBeTruthy();
  });
});

describe("RightPanel", () => {
  it("switches tabs, collapses, and resizes", () => {
    render(<RightPanel loader={loader} />);
    expect(screen.getByRole("tab", { name: "Details" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "Data touched" }));
    expect(screen.getByTestId("data-tab")).toBeTruthy();
    expect((screen.getByTestId("right-panel") as HTMLElement).style.width).toBe("420px");
    Object.defineProperty(window, "innerWidth", { value: 1400, configurable: true });
    fireEvent.mouseDown(screen.getByRole("separator"));
    fireEvent.mouseMove(window, { clientX: 900 });
    fireEvent.mouseUp(window);
    expect(useStore.getState().panelWidth).toBe(500);
    fireEvent.click(screen.getByLabelText("Collapse panel"));
    expect(screen.queryByTestId("right-panel")).toBeNull();
  });
});
