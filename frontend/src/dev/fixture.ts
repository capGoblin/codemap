import type { Anchor, Effect, EffectCategory, EffectOp, Node, TraceGraph } from "../api/types";

const anchor = (symbol: string): Anchor => ({
  file: "app/service.py", start_line: 1, end_line: 20, symbol, content_hash: "h",
});
const fx = (category: EffectCategory, target: string, op: EffectOp): Effect => ({
  category, target, op, fields: [], anchor: anchor(target),
});
function n(
  id: string, level: number, parent: string | null, order: number,
  title: string, input: string, output: string, effects: Effect[] = [], extra: Partial<Node> = {},
): Node {
  return {
    id, level, parent_id: parent, order, title, does: "", input, output,
    boundary_reason: "", anchors: [anchor(title)], effects, parallel_group: null,
    stale: false, warnings: [], ...extra,
  };
}

export const fixtureGraph: TraceGraph = {
  trace: {
    id: "fixture", question: "How is an order placed?", entry: anchor("place_order"),
    commit_sha: null, dirty: false, status: "complete", mode: "eager",
    created_at: "2026-01-01T00:00:00Z", model: "fixture", input_tokens: 0, output_tokens: 0,
    cost_usd: 0,
  },
  nodes: [
    n("p1", 0, null, 0, "Validate request", "HTTP body", "Order draft", [fx("db", "users", "read")]),
    n("p2", 0, null, 1, "Charge and store", "Order draft", "Order id", [
      fx("db", "orders", "write"), fx("http", "payments-api", "call"),
    ]),
    n("p3", 0, null, 2, "Notify", "Order id", "Receipt", [fx("queue", "order-events", "publish")]),
    n("p1.s1", 1, "p1", 0, "Parse body", "HTTP body", "Dict"),
    n("p1.s2", 1, "p1", 1, "Load user", "Dict", "User", [fx("db", "users", "read")]),
    n("p2.s1", 1, "p2", 0, "Charge card", "Order draft", "Payment", [
      fx("http", "payments-api", "call"), fx("cache", "idempotency", "read"),
    ]),
    n("p2.s2", 1, "p2", 1, "Save order", "Payment", "Order id", [
      fx("db", "orders", "write"), fx("db", "order_items", "write"),
      fx("object_store", "invoices", "write"), fx("file", "audit.log", "write"),
      fx("cache", "orders", "write"),
    ], { stale: true }),
    n("p2.s3", 1, "p2", 2, "Payment failed", "Error", "Message", [], {}),
    n("p3.s1", 1, "p3", 0, "Publish event", "Order id", "Message id", [
      fx("queue", "order-events", "publish"),
    ]),
  ],
  edges: [
    { source_id: "p1", target_id: "p2", kind: "call" },
    { source_id: "p2", target_id: "p3", kind: "async" },
    { source_id: "p1.s1", target_id: "p1.s2", kind: "call" },
    { source_id: "p2.s1", target_id: "p2.s2", kind: "call" },
    { source_id: "p2.s1", target_id: "p2.s3", kind: "error" },
  ],
};
