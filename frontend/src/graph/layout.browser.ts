import ELK from "elkjs/lib/elk-api.js";
import elkWorkerUrl from "elkjs/lib/elk-worker.min.js?url";
import { layout, type Box } from "./layout";
import { pageSizer } from "./measure";
import type { VisibleEdge, VisibleNode } from "./visible";

type V = { nodes: VisibleNode[]; edges: VisibleEdge[] };

const TIMEOUT_MS = 10_000;
// ELK's own worker keeps the layout off the main thread.
let elk: InstanceType<typeof ELK> | null = null; // created on first use so importing this file needs no Worker

export function layoutInBrowser(v: V): Promise<Map<string, Box>> {
  return new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error("layout timed out")), TIMEOUT_MS);
    layout(v, (elk ??= new ELK({ workerUrl: elkWorkerUrl })), pageSizer).then(
      (m) => {
        clearTimeout(timer);
        ok(m);
      },
      (e) => {
        clearTimeout(timer);
        fail(e instanceof Error ? e : new Error(String(e)));
      },
    );
  });
}
