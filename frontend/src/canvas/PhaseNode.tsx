import type { NodeProps } from "@xyflow/react";
import { NodeCard, type CardData } from "./NodeCard";

export function PhaseNode({ data }: NodeProps) {
  const d = data as CardData;
  return <NodeCard data={d} caret={d.vn.open ? "▾" : "▸"} />;
}
