import { expandNode } from "../api/client";
import { useStore } from "./store";

// Build the steps of one phase on the server, then merge the new graph.
export async function expandPhase(nodeId: string): Promise<void> {
  const { graph, setExpandError, setExpanding, setGraph } = useStore.getState();
  if (!graph) return;
  setExpandError(nodeId, null);
  setExpanding(nodeId, true);
  try {
    setGraph(await expandNode(graph.trace.id, nodeId));
  } catch (e) {
    setExpandError(nodeId, e instanceof Error ? e.message : String(e));
  } finally {
    setExpanding(nodeId, false);
  }
}

// Click on a phase: toggle it, and in lazy mode build its steps on first open.
export function togglePhase(nodeId: string): void {
  const { graph, openIds, toggleOpen } = useStore.getState();
  const opening = !openIds.has(nodeId);
  toggleOpen(nodeId);
  if (!opening || !graph || graph.trace.mode !== "lazy") return;
  if (graph.nodes.some((n) => n.parent_id === nodeId)) return;
  void expandPhase(nodeId);
}
