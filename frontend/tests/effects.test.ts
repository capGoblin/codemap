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
    expect(opLetter("read")).toBe("R");
    expect(opLetter("write")).toBe("W");
    expect(targetKey(eff("db", "users", "read"))).toBe("db:users");
  });

  it("chipsFor caps at 2, dedupes, and excludes hidden", () => {
    const es = ["a", "b", "c", "d", "e"].map((t) => eff("db", t, "read"));
    const r = chipsFor([...es, es[0]!], new Set());
    expect(r.shown).toHaveLength(2);
    expect(r.more).toBe(3);
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

  it("groups one target by category with one R/W tag per phase and op, in phase order", () => {
    const t = targetsOf(g, new Set()).get("object_store")!;
    expect(t).toHaveLength(1);
    expect(t[0]!.key).toBe("object_store:s3://b");
    expect(t[0]!.tags.map((x) => [x.phaseId, x.op])).toEqual([["P1", "write"], ["P1", "read"]]);
  });

  it("omits hidden categories", () => {
    expect(targetsOf(g, new Set(["object_store"])).has("object_store")).toBe(false);
  });

  it("tags use the top-level phase title for nodes at any depth", () => {
    const deep = {
      trace: {} as TraceGraph["trace"],
      nodes: [
        { ...node("U", 0, null, 0), title: "Upload" },
        { ...node("P", 0, null, 1), title: "Parse" },
        node("p1", 1, "P", 0),
        withEff(node("p2", 2, "p1", 0), [eff("db", "doc", "write")]),
        withEff(node("u1", 1, "U", 0), [eff("db", "doc", "write")]),
      ],
      edges: [],
    } as TraceGraph;
    const t = targetsOf(deep, new Set()).get("db")![0]!;
    expect(t.tags.map((x) => `${opLetter(x.op)} ${x.phaseTitle}`)).toEqual(["W Upload", "W Parse"]);
  });

  it("nodesTouching includes ancestors at any depth", () => {
    expect([...nodesTouching(g, "object_store:s3://b")].sort()).toEqual(["P1", "s1", "s2"]);
    const deep = {
      trace: {} as TraceGraph["trace"],
      nodes: [node("P", 0, null, 0), node("a", 1, "P", 0), withEff(node("b", 2, "a", 0), [eff("db", "t", "read")])],
      edges: [],
    } as TraceGraph;
    expect([...nodesTouching(deep, "db:t")].sort()).toEqual(["P", "a", "b"]);
  });
});
