import { useEffect, useState } from "react";
import type { DetailLoader, FunctionDetail } from "../api/types";
import { fixtureDetailLoader } from "../dev/fixture";
import { useStore } from "../state/store";

export const STALE_WARNING = "Code changed since this trace; snippet may not match.";

type Loaded =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ok"; details: FunctionDetail[] };

function CodeBlock({ code, startLine }: { code: string; startLine: number }) {
  const lines = code.split("\n");
  return (
    <pre className="code">
      {lines.map((l, i) => (
        <div className="code-line" key={i}>
          <span className="ln">{startLine + i}</span>
          <span className="lt">{l}</span>
        </div>
      ))}
    </pre>
  );
}

export function DetailPanel({ loader = fixtureDetailLoader }: { loader?: DetailLoader }) {
  const nodeId = useStore((s) => s.selectedNodeId);
  const graph = useStore((s) => s.graph);
  const selectNode = useStore((s) => s.selectNode);
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const traceId = graph?.trace.id;

  useEffect(() => {
    if (!nodeId || !traceId) return;
    let stale = false;
    setLoaded({ state: "loading" });
    loader(traceId, nodeId).then(
      (detail) => !stale && setLoaded({ state: "ok", details: detail.functions }),
      (e) => !stale && setLoaded({ state: "error", message: String(e) }),
    );
    return () => {
      stale = true;
    };
  }, [traceId, nodeId, loader]);

  const node = graph?.nodes.find((n) => n.id === nodeId);
  if (!node) return null;
  return (
    <section className="panel detail" data-testid="detail-panel">
      <header className="panel-head">
        <h2>{node.title}</h2>
        <button aria-label="Close detail" onClick={() => selectNode(null)}>×</button>
      </header>
      {node.stale && <div className="stale-note">{STALE_WARNING}</div>}
      <ul className="anchors">
        {node.anchors.map((a, i) => (
          <li key={i}>{a.file}:{a.start_line}</li>
        ))}
      </ul>
      <dl className="facts">
        <dt>Input</dt><dd>{node.input}</dd>
        <dt>Does</dt><dd>{node.does}</dd>
        <dt>Output</dt><dd>{node.output}</dd>
        {node.effects.length > 0 && (
          <>
            <dt>Effects</dt>
            <dd>{node.effects.map((e) => `${e.op} ${e.target}`).join(", ")}</dd>
          </>
        )}
      </dl>
      {loaded.state === "loading" && <div className="muted">Loading code…</div>}
      {loaded.state === "error" && <div className="err">Could not load code: {loaded.message}</div>}
      {loaded.state === "ok" &&
        loaded.details.map((d, i) => (
          <div className="fn" key={i}>
            <div className="sig">{d.signature}</div>
            <div className="muted">{d.anchor.file}:{d.anchor.start_line}</div>
            <CodeBlock code={d.code} startLine={d.anchor.start_line} />
            {d.calls.length > 0 && (
              <>
                <div className="sub">Calls</div>
                <ul className="calls">
                  {d.calls.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ))}
    </section>
  );
}
