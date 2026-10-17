// Hand-written mirror of src/codemap/domain/models.py.
// A later task replaces this file with a re-export of the generated types.

export type EffectCategory =
  | "db" | "object_store" | "queue" | "cache" | "file" | "workflow" | "http" | "other";
export type EffectOp = "read" | "write" | "delete" | "publish" | "consume" | "call";
export type EdgeKind = "call" | "async" | "error" | "branch";

export interface Anchor {
  file: string;
  start_line: number;
  end_line: number;
  symbol: string;
  content_hash: string;
}

export interface Effect {
  category: EffectCategory;
  target: string;
  op: EffectOp;
  fields: string[];
  anchor: Anchor;
}

export interface Node {
  id: string;
  level: number;
  parent_id: string | null;
  order: number;
  title: string;
  does: string;
  input: string;
  output: string;
  boundary_reason: string;
  anchors: Anchor[];
  effects: Effect[];
  parallel_group: number | null;
  stale: boolean;
  warnings: string[];
}

export interface Edge {
  source_id: string;
  target_id: string;
  kind: EdgeKind;
}

export interface Trace {
  id: string;
  question: string;
  entry: Anchor;
  commit_sha: string | null;
  dirty: boolean;
  status: "running" | "complete" | "partial" | "failed";
  mode: "eager" | "lazy";
  created_at: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TraceGraph {
  trace: Trace;
  nodes: Node[];
  edges: Edge[];
}

export interface FunctionDetail {
  anchor: Anchor;
  signature: string;
  code: string;
  calls: string[];
}
