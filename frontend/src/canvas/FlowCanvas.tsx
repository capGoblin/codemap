import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background, ReactFlow, useReactFlow,
  type Edge as RFEdge, type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/canvas.css";
import { buildVisible, type VisibleEdge, type VisibleNode } from "../graph/visible";
import { layoutInWorker } from "../graph/layout.worker";
import type { Box } from "../graph/layout";
import { nodesTouching } from "../effects/categories";
import { useStore, type CameraRequest } from "../state/store";
import { PhaseNode } from "./PhaseNode";
import { StepNode } from "./StepNode";
import { edgeTypes } from "./edges";

const nodeTypes = { phase: PhaseNode, step: StepNode };

type V = { nodes: VisibleNode[]; edges: VisibleEdge[] };
export type LayoutFn = (v: V) => Promise<Map<string, Box>>;

export function FlowCanvas({ layoutFn = layoutInWorker }: { layoutFn?: LayoutFn }) {
  const graph = useStore((s) => s.graph);
  const openIds = useStore((s) => s.openIds);
  const selectedTarget = useStore((s) => s.selectedTarget);
  const { fitView } = useReactFlow();
  const [laid, setLaid] = useState<{ v: V; boxes: Map<string, Box> } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const firstLayout = useRef(true); // the first layout fits everything
  const fitPending = useRef<CameraRequest>(null);

  useEffect(() => {
    if (!graph) return;
    let stale = false;
    const v = buildVisible(graph, openIds);
    layoutFn(v).then(
      (boxes) => {
        if (stale) return;
        const req = useStore.getState().takeCameraRequest();
        fitPending.current = req ?? (firstLayout.current ? { kind: "all" } : null);
        firstLayout.current = false;
        setLayoutError(null);
        setLaid({ v, boxes });
      },
      (e) => !stale && setLayoutError(String(e)),
    );
    return () => {
      stale = true;
    };
  }, [graph, openIds, layoutFn]);

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
        type: vn.kind,
        position: { x: b.x, y: b.y },
        ...(vn.parentId ? { parentId: vn.parentId, extent: "parent" as const } : {}),
        style: { width: b.width, height: b.height },
        data: { vn, faded: touching !== null && !touching.has(vn.id) },
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
  }, [laid, touching]);

  useEffect(() => {
    const req = fitPending.current;
    if (!req || nodes.length === 0) return;
    fitPending.current = null;
    const t = setTimeout(() => {
      if (req.kind === "focus") {
        void fitView({ nodes: [{ id: req.id }], padding: 0.25, duration: 400 });
      } else {
        void fitView({ duration: 400 });
      }
    }, 0);
    return () => clearTimeout(t);
  }, [nodes, fitView]);

  const { selectNode, toggleOpen } = useStore.getState();
  return (
    <>
      {layoutError && <div className="banner-err">Layout failed: {layoutError}</div>}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.1}
        onNodeClick={(_, n) => {
          const vn = (n.data as { vn: VisibleNode }).vn;
          if (vn.kind === "phase") toggleOpen(vn.id);
          else selectNode(vn.id);
        }}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>
    </>
  );
}
