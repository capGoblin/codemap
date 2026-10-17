import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from "@xyflow/react";
import type { EdgeKind } from "../api/types";

export type FlowEdgeData = { kind: EdgeKind; dimmed: boolean; [k: string]: unknown };

export function FlowEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition } = props;
  const data = props.data as FlowEdgeData;
  const [path, lx, ly] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  });
  const async_ = data.kind === "async";
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        style={{
          stroke: async_ ? "var(--edge-async)" : "var(--edge)",
          strokeWidth: 1.5,
          strokeDasharray: async_ ? "6 4" : undefined,
          opacity: data.dimmed ? 0.35 : 1,
        }}
        markerEnd={props.markerEnd}
      />
      {async_ && (
        <EdgeLabelRenderer>
          <div
            className="edge-label"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
          >
            async
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes = { flow: FlowEdge };
