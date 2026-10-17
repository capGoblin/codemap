// Thin aliases over the generated schema (`make gen-api` rewrites schema.d.ts).
import type { components } from "./schema";

type S = components["schemas"];

export type Anchor = S["Anchor"];
export type Effect = S["Effect"];
export type Node = S["Node"];
export type Edge = S["Edge"];
export type Trace = S["Trace"];
export type TraceGraph = S["TraceGraph"];
export type FunctionDetail = S["FunctionDetail"];
export type NodeDetail = S["NodeDetail"];
export type NodeExplain = S["NodeExplain"];
export type ExplainStep = S["ExplainStep"];
export type IoSide = S["IoSide"];
export type CallLink = S["CallLink"];
export type EffectCategory = Effect["category"];
export type EffectOp = Effect["op"];
export type EdgeKind = Edge["kind"];

export type DetailLoader = (traceId: string, nodeId: string) => Promise<NodeDetail>;
export type DetailRegenerator = DetailLoader;
