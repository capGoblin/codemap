import { expandNode } from "../api/client";
import { useStore } from "./store";

// Ask the server to split one node. Any node may open; the server decides if it has sub-steps.
export async function expandChildren(nodeId: string): Promise<void> {
  const { graph, setExpandError, setExpanding, setGraph, markLeaf } = useStore.getState();
  if (!graph) return;
  setExpandError(nodeId, null);
  setExpanding(nodeId, true);
  try {
    const next = await expandNode(graph.trace.id, nodeId);
    setGraph(next);
    if (!next.nodes.some((n) => n.parent_id === nodeId)) markLeaf(nodeId);
  } catch (e) {
    setExpandError(nodeId, e instanceof Error ? e.message : String(e));
  } finally {
    setExpanding(nodeId, false);
  }
}

// Click on a node: select it, toggle it, and build its children on first open.
export function toggleNode(nodeId: string): void {
  const { graph, openIds, toggleOpen } = useStore.getState();
  const opening = !openIds.has(nodeId);
  toggleOpen(nodeId);
  if (!opening || !graph) return;
  if (graph.nodes.some((n) => n.parent_id === nodeId)) return;
  void expandChildren(nodeId);
}
