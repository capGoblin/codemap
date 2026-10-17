import { useEffect, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { getDetail, getGraph, getTraces } from "./api/client";
import type { DetailLoader, Trace, TraceGraph } from "./api/types";
import { FlowCanvas, type LayoutFn } from "./canvas/FlowCanvas";
import { DetailPanel } from "./panels/DetailPanel";
import { EffectPanel } from "./panels/EffectPanel";
import { EffectLane } from "./effects/EffectLane";
import { Toolbar } from "./Toolbar";
import { useStore } from "./state/store";
import { fixtureGraph } from "./dev/fixture";

// Matches /traces/:id. Returns null for any other path.
export function traceIdFromPath(path: string): string | null {
  const m = /^\/traces\/([^/]+)\/?$/.exec(path);
  return m ? decodeURIComponent(m[1]!) : null;
}

type Props = { graph?: TraceGraph; layoutFn?: LayoutFn; detailLoader?: DetailLoader };

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function TraceList() {
  const [traces, setTraces] = useState<Trace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getTraces().then(setTraces, (e: unknown) => setError(errorText(e)));
  }, []);
  return (
    <div className="trace-list">
      {error && <div className="banner-err">Could not load traces: {error}</div>}
      <h1>Traces</h1>
      {traces?.length === 0 && <p>No traces for this repo yet.</p>}
      <ul>
        {traces?.map((t) => (
          <li key={t.id}>
            <a href={`/traces/${encodeURIComponent(t.id)}`}>{t.question}</a> ({t.status})
          </li>
        ))}
      </ul>
    </div>
  );
}

export function App({ graph, layoutFn, detailLoader }: Props) {
  const setGraph = useStore((s) => s.setGraph);
  const traceId = traceIdFromPath(window.location.pathname);
  const [error, setError] = useState<string | null>(null);
  const useApi = !graph && traceId !== null;
  const showList = !graph && traceId === null && !import.meta.env.DEV;

  useEffect(() => {
    if (graph) setGraph(graph);
    else if (traceId !== null) {
      let live = true;
      getGraph(traceId, 1).then(
        (g) => live && setGraph(g),
        (e: unknown) => live && setError(`Could not load trace ${traceId}: ${errorText(e)}`),
      );
      return () => {
        live = false;
      };
    } else if (import.meta.env.DEV) setGraph(fixtureGraph);
  }, [graph, traceId, setGraph]);

  if (showList) return <TraceList />;
  const loader = detailLoader ?? (useApi ? getDetail : undefined);

  return (
    <ReactFlowProvider>
      <div className="app">
        {error && <div className="banner-err">{error}</div>}
        <Toolbar />
        <div className="main">
          <div className="canvas">
            <FlowCanvas {...(layoutFn ? { layoutFn } : {})} />
          </div>
          <aside className="drawer">
            <EffectPanel />
            <DetailPanel {...(loader ? { loader } : {})} />
          </aside>
        </div>
        <EffectLane />
      </div>
    </ReactFlowProvider>
  );
}
