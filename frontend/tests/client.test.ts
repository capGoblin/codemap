import { afterEach, expect, test, vi } from "vitest";
import { ApiError, expandNode, getDetail, getGraph, getTraces } from "../src/api/client";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

test("a 404 throws ApiError with the status and detail", async () => {
  mockFetch(404, { detail: "not found: t9" });
  const err = await getGraph("t9", 1).catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect((err as ApiError).status).toBe(404);
  expect((err as ApiError).message).toBe("not found: t9");
});

test("a non-JSON error body falls back to the status text", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500, statusText: "Oops" })));
  await expect(getTraces()).rejects.toMatchObject({ status: 500, message: "Oops" });
});

test("requests use the right URLs and methods", async () => {
  const fn = mockFetch(200, []);
  await getTraces();
  await getGraph("a b", 2);
  await expandNode("t1", "p1");
  await getDetail("t1", "p1.s1");
  const calls = fn.mock.calls as unknown as [string, RequestInit?][];
  expect(calls.map((c) => c[0])).toEqual([
    "/api/v1/traces",
    "/api/v1/traces/a%20b?depth=2",
    "/api/v1/traces/t1/nodes/p1/expand",
    "/api/v1/traces/t1/nodes/p1.s1/detail",
  ]);
  expect(calls[2]![1]?.method).toBe("POST");
});
