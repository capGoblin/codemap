import { useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import type { TraceGraph } from "./api/types";
import { FlowCanvas, type LayoutFn } from "./canvas/FlowCanvas";
import { Toolbar } from "./Toolbar";
import { useStore } from "./state/store";
import { fixtureGraph } from "./dev/fixture";

// Matches /traces/:id. Returns null for any other path.
export function traceIdFromPath(path: string): string | null {
  const m = /^\/traces\/([^/]+)\/?$/.exec(path);
  return m ? decodeURIComponent(m[1]!) : null;
}

type Props = { graph?: TraceGraph; layoutFn?: LayoutFn };

export function App({ graph, layoutFn }: Props) {
  const setGraph = useStore((s) => s.setGraph);
  // No API client yet (it will use traceIdFromPath): use the prop, else the fixture.
  useEffect(() => {
    setGraph(graph ?? fixtureGraph);
  }, [graph, setGraph]);

  return (
    <ReactFlowProvider>
      <div className="app">
        <Toolbar />
        <div className="canvas">
          <FlowCanvas {...(layoutFn ? { layoutFn } : {})} />
        </div>
      </div>
    </ReactFlowProvider>
  );
}
