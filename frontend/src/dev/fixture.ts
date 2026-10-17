import type {
  Anchor, DetailLoader, Effect, EffectCategory, EffectOp, FunctionDetail, Node, NodeExplain, TraceGraph,
} from "../api/types";

const anchor = (symbol: string): Anchor => ({
  file: "app/service.py", start_line: 1, end_line: 20, symbol, content_hash: "h",
});
const fx = (category: EffectCategory, target: string, op: EffectOp): Effect => ({
  category, target, op, fields: [], anchor: anchor(target),
});
function n(
  id: string, level: number, parent: string | null, order: number,
  title: string, summary: string, effects: Effect[] = [], extra: Partial<Node> = {},
): Node {
  return {
    id, level, parent_id: parent, order, title, summary, does: "", input: "", output: "",
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
    n("p1", 0, null, 0, "Validate request", "Check the body and load the calling user.", [fx("db", "users", "read")]),
    n("p2", 0, null, 1, "Charge and store", "Take payment, then save the order and its items.", [
      fx("db", "orders", "write"), fx("http", "payments-api", "read"),
    ]),
    n("p3", 0, null, 2, "Notify", "Publish an order event for downstream consumers.", [fx("queue", "order-events", "write")]),
    n("p1.s1", 1, "p1", 0, "Parse body", "Turn the HTTP body into a dict."),
    n("p1.s2", 1, "p1", 1, "Load user", "Fetch the user row by id.", [fx("db", "users", "read")]),
    n("p2.s1", 1, "p2", 0, "Charge card", "Call the payment provider with an idempotency key.", [
      fx("http", "payments-api", "read"), fx("cache", "idempotency", "read"),
    ]),
    n("p2.s2", 1, "p2", 1, "Save order", "Write the order, its items, the invoice and an audit line.", [
      fx("db", "orders", "write"), fx("db", "order_items", "write"),
      fx("object_store", "invoices", "write"), fx("file", "audit.log", "write"),
      fx("cache", "orders", "write"),
    ], { stale: true }),
    n("p2.s3", 1, "p2", 2, "Payment failed", "Return an error message to the caller."),
    n("p2.s2.a", 2, "p2.s2", 0, "Insert order rows", "Add the order and one row per item.", [
      fx("db", "orders", "write"), fx("db", "order_items", "write"),
    ]),
    n("p2.s2.b", 2, "p2.s2", 1, "Store invoice", "Render the invoice and put it in the bucket.", [
      fx("object_store", "invoices", "write"),
    ]),
    n("p3.s1", 1, "p3", 0, "Publish event", "Send the order id to the events queue.", [
      fx("queue", "order-events", "write"),
    ]),
  ],
  edges: [
    { source_id: "p1", target_id: "p2", kind: "call" },
    { source_id: "p2", target_id: "p3", kind: "async" },
    { source_id: "p1.s1", target_id: "p1.s2", kind: "call" },
    { source_id: "p2.s1", target_id: "p2.s2", kind: "call" },
    { source_id: "p2.s1", target_id: "p2.s3", kind: "error" },
    { source_id: "p2.s2.a", target_id: "p2.s2.b", kind: "call" },
  ],
};

const saveOrderCode = `def save_order(payment, draft):
    order = Order(user_id=draft.user_id, payment_id=payment.id)
    db.session.add(order)
    for item in draft.items:
        db.session.add(OrderItem(order=order, sku=item.sku, qty=item.qty))
    db.session.commit()
    invoices.put(f"{order.id}.pdf", render_invoice(order))
    audit_log.write(f"order {order.id} saved")
    cache.set(f"orders:{order.id}", order.to_json())
    return order.id`;

const detailFixtures: Record<string, FunctionDetail[]> = {
  "p2.s2": [
    {
      anchor: { ...anchor("save_order"), start_line: 48, end_line: 57 },
      signature: "def save_order(payment: Payment, draft: OrderDraft) -> str",
      code: saveOrderCode,
      calls: ["Order", "OrderItem", "render_invoice", "invoices.put", "cache.set"],
    },
    {
      anchor: { ...anchor("render_invoice"), start_line: 72, end_line: 75 },
      signature: "def render_invoice(order: Order) -> bytes",
      code: `def render_invoice(order):\n    html = template.render(order=order)\n    return pdf.from_html(html)`,
      calls: ["template.render", "pdf.from_html"],
    },
  ],
};

const saveExplain: NodeExplain = {
  steps: [
    { text: "Create the order and add one row per item.", file: "app/service.py", lines: [49, 52] },
    { text: "Commit, then store the invoice PDF.", file: "app/service.py", lines: [53, 54] },
    { text: "Write the audit line and cache the order.", file: "app/service.py", lines: [55, 56] },
  ],
  input: { type: "Payment, OrderDraft", fields: ["payment.id", "draft.items"], node_id: "p2.s1" },
  output: { type: "str (order id)", fields: [], node_id: "p3" },
};

// Dev-only loader: any node without a fixture gets a stub.
export const fixtureDetailLoader: DetailLoader = async (_traceId, nodeId) => ({
  explain: nodeId === "p2.s2" ? saveExplain : null,
  explain_error: nodeId === "p2.s2" ? null : "no model in the fixture",
  calls: nodeId === "p2.s2" ? [{ symbol: "render_invoice", node_id: "p2.s2.b" }, { symbol: "cache.set", node_id: null }] : [],
  effects:
    nodeId === "p2.s2"
      ? [{ ...fx("db", "orders", "write"), anchor: { ...anchor("save_order"), start_line: 50, end_line: 50 } }]
      : [],
  functions: detailFixtures[nodeId] ?? [
    {
      anchor: anchor(nodeId),
      signature: `def ${nodeId.replace(/\W/g, "_")}(request)`,
      code: `def ${nodeId.replace(/\W/g, "_")}(request):\n    data = request.json()\n    return handle(data)`,
      calls: ["handle"],
    },
  ],
});
