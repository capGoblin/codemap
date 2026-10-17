import { useEffect, useRef } from "react";

export type TraceEvent = { kind: string; message: string };

const KINDS = ["step_started", "hop_found", "hop_verified", "phase_split", "warning", "finished"];

// Subscribe to a trace's event stream. Close it on `finished`.
// While the trace is not running, a dropped stream is not reopened.
export function useTraceEvents(
  traceId: string | null,
  onEvent: (e: TraceEvent) => void,
  running = true,
): void {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const isRunning = useRef(running);
  isRunning.current = running;

  useEffect(() => {
    if (traceId === null) return;
    const es = new EventSource(`/api/v1/traces/${encodeURIComponent(traceId)}/events`);
    for (const kind of KINDS) {
      es.addEventListener(kind, (m) => {
        let message = "";
        try {
          message = (JSON.parse((m as MessageEvent<string>).data) as { message?: string }).message ?? "";
        } catch {
          // A malformed payload still counts as an event of that kind.
        }
        handler.current({ kind, message });
        if (kind === "finished") es.close();
      });
    }
    es.onerror = () => {
      if (!isRunning.current) es.close();
    };
    return () => es.close();
  }, [traceId]);
}
