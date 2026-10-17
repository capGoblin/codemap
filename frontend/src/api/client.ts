import type { FunctionDetail, Trace, TraceGraph } from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the status text when the body is not JSON.
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const getTraces = (): Promise<Trace[]> => request("/traces");

export const getGraph = (id: string, depth: number): Promise<TraceGraph> =>
  request(`/traces/${enc(id)}?depth=${depth}`);

export const expandNode = (id: string, nodeId: string): Promise<TraceGraph> =>
  request(`/traces/${enc(id)}/nodes/${enc(nodeId)}/expand`, { method: "POST" });

export const getDetail = (id: string, nodeId: string): Promise<FunctionDetail[]> =>
  request(`/traces/${enc(id)}/nodes/${enc(nodeId)}/detail`);
