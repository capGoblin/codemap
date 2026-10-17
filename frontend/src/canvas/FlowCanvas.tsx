import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background, ReactFlow, useReactFlow,
  type Edge as RFEdge, type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/canvas.css";
import { buildVisible, type VisibleEdge, type VisibleNode } from "../graph/visible";
import { layoutInBrowser } from "../graph/layout.browser";
import type { Box } from "../graph/layout";
import { nodesTouching } from "../effects/categories";
import { useStore, type CameraRequest } from "../state/store";
import { toggleNode } from "../state/expand";
import { NodeCard } from "./NodeCard";
import { edgeTypes } from "./edges";

const nodeTypes = { card: NodeCard };

type V = { nodes: VisibleNode[]; edges: VisibleEdge[] };
export type LayoutFn = (v: V) => Promise<Map<string, Box>>;

export function FlowCanvas({ layoutFn = layoutInBrowser }: { layoutFn?: LayoutFn }) {
  const graph = useStore((s) => s.graph);
  const openIds = useStore((s) => s.openIds);
  const selectedTarget = useStore((s) => s.selectedTarget);
  const hidden = useStore((s) => s.hiddenCategories);
  const leaves = useStore((s) => s.leaves);
  const selectedId = useStore((s) => s.selectedNodeId);
  const { fitView } = useReactFlow();
  const [laid, setLaid] = useState<{ v: V; boxes: Map<string, Box> } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const fitPending = useRef<CameraRequest>(null);

  useEffect(() => {
    if (!graph) return;
    let stale = false;
    const v = buildVisible(graph, openIds, hidden, leaves);
    layoutFn(v).then(
      (boxes) => {
        if (stale) return;
        const req = useStore.getState().takeCameraRequest();
        // The first fit is done by the <ReactFlow fitView> prop once nodes are measured.
        fitPending.current = req;
        setLayoutError(null);
        setLaid({ v, boxes });
      },
      (e) => !stale && setLayoutError(String(e)),
    );
    return () => {
      stale = true;
    };
  }, [graph, openIds, hidden, leaves, layoutFn]);

  const touching = useMemo(
    () => (graph && selectedTarget ? nodesTouching(graph, selectedTarget) : null),
    [graph, selectedTarget],
  );

  const { nodes, edges } = useMemo(() => {
    if (!laid) return { nodes: [] as RFNode[], edges: [] as RFEdge[] };
    const nodes: RFNode[] = [];
    for (const vn of laid.v.nodes) {
      const b = laid.boxes.get(vn.id);
      if (!b) continue;
      nodes.push({
        id: vn.id,
        type: "card",
        position: { x: b.x, y: b.y },
        ...(vn.parentId ? { parentId: vn.parentId, extent: "parent" as const } : {}),
        style: { width: b.width, height: b.height },
        data: { vn, faded: touching !== null && !touching.has(vn.id), selected: vn.id === selectedId },
        draggable: false,
      });
    }
    const edges: RFEdge[] = laid.v.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "flow",
      data: { kind: e.kind, dimmed: e.dimmed },
    }));
    return { nodes, edges };
  }, [laid, touching, selectedId]);

  useEffect(() => {
    const req = fitPending.current;
    if (!req || nodes.length === 0) return;
    fitPending.current = null;
    // No cleanup: the request is already taken, so cancelling would drop it.
    setTimeout(() => {
      if (req.kind === "focus") {
        void fitView({ nodes: [{ id: req.id }], padding: 0.25, maxZoom: 1, duration: 400 });
      } else {
        void fitView({ maxZoom: 1, duration: 400 });
      }
    }, 0);
  }, [nodes]); // eslint-disable-line react-hooks/exhaustive-deps

  const { selectNode } = useStore.getState();
  return (
    <>
      {layoutError && <div className="banner-err">Layout failed: {layoutError}</div>}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.15 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.1}
        onNodeClick={(_, n) => {
          const vn = (n.data as { vn: VisibleNode }).vn;
          selectNode(vn.id);
          if (vn.expandable) toggleNode(vn.id);
        }}
      >
        <Background />
      </ReactFlow>
    </>
  );
}
