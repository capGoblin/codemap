import { describe, expect, it } from "vitest";
import type { Effect, TraceGraph } from "../src/api/types";
import {
  CATEGORY_LABEL, chipsFor, nodesTouching, opLetter, targetKey, targetsOf, uiCategory,
} from "../src/effects/categories";
import { node } from "./helpers";

const eff = (category: Effect["category"], target: string, op: Effect["op"], fields: string[] = []): Effect => ({
  category, target, op, fields,
  anchor: { file: "a.py", start_line: 1, end_line: 1, symbol: "f", content_hash: "" },
});

describe("categories", () => {
  it("maps categories and ops", () => {
    expect(uiCategory("workflow")).toBe("queue_workflow");
    expect(uiCategory("queue")).toBe("queue_workflow");
    expect(uiCategory("http")).toBe("external");
    expect(uiCategory("other")).toBe("external");
    expect(uiCategory("db")).toBe("db");
    expect(CATEGORY_LABEL.queue_workflow).toBe("Queue / Workflow");
    expect(opLetter("consume")).toBe("P");
    expect(opLetter("write")).toBe("W");
    expect(targetKey(eff("db", "users", "read"))).toBe("db:users");
  });

  it("chipsFor caps at 3 and excludes hidden", () => {
    const es = ["a", "b", "c", "d", "e"].map((t) => eff("db", t, "read"));
    const r = chipsFor(es, new Set());
    expect(r.shown).toHaveLength(3);
    expect(r.more).toBe(2);
    const mixed = [...es, eff("cache", "k", "read")];
    expect(chipsFor(mixed, new Set(["db"]))).toEqual({ shown: [mixed[5]], more: 0 });
  });
});

describe("graph helpers", () => {
  const withEff = (n: ReturnType<typeof node>, effects: Effect[]) => ({ ...n, effects });
  const g = {
    trace: {} as TraceGraph["trace"],
    nodes: [
      node("P1", 0, null, 0),
      withEff(node("s1", 1, "P1", 0), [eff("object_store", "s3://b", "write", ["x"])]),
      withEff(node("s2", 1, "P1", 1), [eff("object_store", "s3://b", "read"), eff("db", "users", "read")]),
      withEff(node("P2", 0, null, 1), [eff("cache", "k", "read")]),
    ],
    edges: [],
  } as TraceGraph;

  it("groups S3 write and read under one target", () => {
    const t = targetsOf(g, new Set()).get("object_store")!;
    expect(t).toHaveLength(1);
    expect(t[0]!.key).toBe("object_store:s3://b");
    expect(t[0]!.uses.map((u) => [u.nodeId, u.op])).toEqual([["s1", "write"], ["s2", "read"]]);
    expect(t[0]!.uses[0]!.fields).toEqual(["x"]);
  });

  it("omits hidden categories", () => {
    expect(targetsOf(g, new Set(["object_store"])).has("object_store")).toBe(false);
  });

  it("uses phases only when a phase has no steps", () => {
    expect(targetsOf(g, new Set()).get("cache")![0]!.uses[0]!.nodeId).toBe("P2");
  });

  it("nodesTouching includes the parent phase", () => {
    expect([...nodesTouching(g, "object_store:s3://b")].sort()).toEqual(["P1", "s1", "s2"]);
  });
});
