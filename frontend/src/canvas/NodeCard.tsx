import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { VisibleNode } from "../graph/visible";
import { caretOf } from "../graph/measure";
import { targetKey } from "../effects/categories";
import { useStore } from "../state/store";
import { CardBody } from "./CardBody";

export type CardData = { vn: VisibleNode; faded: boolean; selected: boolean; [k: string]: unknown };

export function opacityOf(vn: VisibleNode, faded: boolean): number {
  if (faded) return 0.3;
  return vn.dimmed ? 0.35 : 1;
}

// The one card for every level. An open node with children is drawn as a frame (header only).
export function NodeCard({ data }: NodeProps) {
  const { vn, faded, selected } = data as CardData;
  const expanding = useStore((s) => s.expanding.has(vn.id));
  const { selectTarget, showPanel } = useStore.getState();
  return (
    <div
      className={`card-wrap${vn.container ? " frame" : ""}${selected ? " sel" : ""}`}
      data-testid={`node-${vn.id}`}
      style={{ opacity: opacityOf(vn, faded) }}
    >
      <Handle type="target" position={Position.Left} />
      <CardBody
        node={vn.node}
        depth={vn.depth}
        chips={vn.chips}
        caret={caretOf(vn)}
        variant={vn.container ? "header" : "card"}
        onChip={(e) => {
          selectTarget(targetKey(e));
          showPanel("data");
        }}
      />
      {expanding && <span className="spinner" role="status" aria-label="Expanding" />}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
