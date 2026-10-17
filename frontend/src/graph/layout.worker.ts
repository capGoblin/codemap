import { layout, type Box } from "./layout";
import type { VisibleEdge, VisibleNode } from "./visible";

type V = { nodes: VisibleNode[]; edges: VisibleEdge[] };
type Req = { id: number; v: V };
type Res = { id: number; boxes?: [string, Box][]; error?: string };

// Worker side: runs only when this file is loaded as a Worker.
if (typeof WorkerGlobalScope !== "undefined" && self instanceof WorkerGlobalScope) {
  self.onmessage = async (ev: MessageEvent<Req>) => {
    const { id, v } = ev.data;
    try {
      const boxes = [...(await layout(v)).entries()];
      self.postMessage({ id, boxes } satisfies Res);
    } catch (e) {
      self.postMessage({ id, error: String(e) } satisfies Res);
    }
  };
}

let worker: Worker | null = null;
let nextId = 0;
const pending = new Map<number, { ok: (m: Map<string, Box>) => void; fail: (e: Error) => void }>();

export function layoutInWorker(v: V): Promise<Map<string, Box>> {
  if (!worker) {
    worker = new Worker(new URL("./layout.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (ev: MessageEvent<Res>) => {
      const p = pending.get(ev.data.id);
      if (!p) return;
      pending.delete(ev.data.id);
      if (ev.data.error !== undefined) p.fail(new Error(ev.data.error));
      else p.ok(new Map(ev.data.boxes));
    };
  }
  const id = nextId++;
  return new Promise((ok, fail) => {
    pending.set(id, { ok, fail });
    worker!.postMessage({ id, v } satisfies Req);
  });
}
