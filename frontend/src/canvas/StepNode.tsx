import type { NodeProps } from "@xyflow/react";
import { NodeCard, type CardData } from "./NodeCard";

export function StepNode({ data }: NodeProps) {
  return <NodeCard data={data as CardData} />;
}
