import { create } from "zustand";
import type { TraceGraph } from "../api/types";
import type { UiCategory } from "../effects/categories";

export type CameraRequest = { kind: "focus"; id: string } | { kind: "all" } | null;

type State = {
  graph: TraceGraph | null;
  openIds: Set<string>;
  selectedNodeId: string | null;
  selectedTarget: string | null; // key "category:target"
  hiddenCategories: Set<UiCategory>;
  cameraRequest: CameraRequest; // one-shot: consumed by the next layout
  expandErrors: Map<string, string>;
  expanding: Set<string>; // phases with a lazy expand request in flight
};

type Actions = {
  setGraph: (g: TraceGraph) => void;
  toggleOpen: (id: string) => void;
  expandAll: () => void;
  collapseAll: () => void;
  takeCameraRequest: () => CameraRequest;
  selectNode: (id: string | null) => void;
  focusNode: (id: string) => void;
  selectTarget: (key: string | null) => void;
  toggleCategory: (c: UiCategory) => void;
  setExpandError: (id: string, msg: string | null) => void;
  setExpanding: (id: string, on: boolean) => void;
};

export const useStore = create<State & Actions>((set, get) => ({
  graph: null,
  openIds: new Set(),
  selectedNodeId: null,
  selectedTarget: null,
  hiddenCategories: new Set(),
  cameraRequest: null,
  expandErrors: new Map(),
  expanding: new Set(),

  // Keep open phases across refetches; drop only ids that no longer exist.
  setGraph: (graph) =>
    set((s) => {
      const ids = new Set(graph.nodes.map((n) => n.id));
      const kept = [...s.openIds].filter((id) => ids.has(id));
      return kept.length === s.openIds.size
        ? { graph }
        : { graph, openIds: new Set(kept) };
    }),
  toggleOpen: (id) =>
    set((s) => {
      const openIds = new Set(s.openIds);
      if (openIds.delete(id)) return { openIds };
      openIds.add(id);
      return { openIds, cameraRequest: { kind: "focus", id } };
    }),
  expandAll: () =>
    set((s) => ({
      openIds: new Set((s.graph?.nodes ?? []).filter((n) => n.level === 0).map((n) => n.id)),
      cameraRequest: { kind: "all" },
    })),
  collapseAll: () => set({ openIds: new Set() }),
  takeCameraRequest: () => {
    const r = get().cameraRequest;
    if (r) set({ cameraRequest: null });
    return r;
  },
  selectNode: (selectedNodeId) => set({ selectedNodeId }),
  focusNode: (id) =>
    set((s) => {
      const parent = s.graph?.nodes.find((n) => n.id === id)?.parent_id ?? null;
      const openIds = new Set(s.openIds);
      if (parent !== null) openIds.add(parent);
      return { openIds, cameraRequest: { kind: "focus", id } };
    }),
  selectTarget: (selectedTarget) => set({ selectedTarget }),
  toggleCategory: (c) =>
    set((s) => {
      const hiddenCategories = new Set(s.hiddenCategories);
      if (!hiddenCategories.delete(c)) hiddenCategories.add(c);
      return { hiddenCategories };
    }),
  setExpandError: (id, msg) =>
    set((s) => {
      const expandErrors = new Map(s.expandErrors);
      if (msg === null) expandErrors.delete(id);
      else expandErrors.set(id, msg);
      return { expandErrors };
    }),
  setExpanding: (id, on) =>
    set((s) => {
      const expanding = new Set(s.expanding);
      if (on) expanding.add(id);
      else expanding.delete(id);
      return { expanding };
    }),
}));
