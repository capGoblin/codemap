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
};

type Actions = {
  setGraph: (g: TraceGraph) => void;
  toggleOpen: (id: string) => void;
  expandAll: () => void;
  collapseAll: () => void;
  requestFit: () => void;
  takeCameraRequest: () => CameraRequest;
  selectNode: (id: string | null) => void;
  selectTarget: (key: string | null) => void;
  toggleCategory: (c: UiCategory) => void;
  setExpandError: (id: string, msg: string | null) => void;
};

export const useStore = create<State & Actions>((set, get) => ({
  graph: null,
  openIds: new Set(),
  selectedNodeId: null,
  selectedTarget: null,
  hiddenCategories: new Set(),
  cameraRequest: null,
  expandErrors: new Map(),

  setGraph: (graph) => set({ graph }),
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
  requestFit: () => set({ cameraRequest: { kind: "all" } }),
  takeCameraRequest: () => {
    const r = get().cameraRequest;
    if (r) set({ cameraRequest: null });
    return r;
  },
  selectNode: (selectedNodeId) => set({ selectedNodeId }),
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
}));
