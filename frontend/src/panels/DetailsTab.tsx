import { useEffect, useMemo, useState } from "react";
import type { DetailLoader, Effect, IoSide, NodeDetail } from "../api/types";
import { opLetter } from "../effects/categories";
import { useStore } from "../state/store";
import { CodeView, citeLabel, type Cite } from "./CodeView";

export const STALE_WARNING = "Code changed since this trace; snippet may not match.";

type Load =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ok"; detail: NodeDetail; retrying: boolean };

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" data-testid="skeleton" aria-busy="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="sk-line" style={{ width: `${95 - i * 14}%` }} />
      ))}
    </div>
  );
}

function CiteLink({ cite, onCite }: { cite: Cite; onCite: (c: Cite) => void }) {
  return (
    <button type="button" className="cite" title={cite.file} onClick={() => onCite(cite)}>
      {citeLabel(cite)}
    </button>
  );
}

function NodeLink({ id, label }: { id: string; label: string }) {
  const focusNode = useStore((s) => s.focusNode);
  const selectNode = useStore((s) => s.selectNode);
  return (
    <button
      type="button"
      className="link"
      onClick={() => {
        focusNode(id);
        selectNode(id);
      }}
    >
      {label}
    </button>
  );
}

function IoBox({ kind, side }: { kind: "Input" | "Output"; side: IoSide }) {
  const nodes = useStore((s) => s.graph?.nodes);
  const other = side.node_id ? nodes?.find((n) => n.id === side.node_id) : undefined;
  return (
    <div className="io-box" data-testid={`io-${kind.toLowerCase()}`}>
      <div className="io-k">{kind}</div>
      <div className="io-type">{side.type || "—"}</div>
      {side.fields.length > 0 && <div className="io-fields">{side.fields.join(", ")}</div>}
      {other && (
        <div className="io-from">
          {kind === "Input" ? "from " : "to "}
          <NodeLink id={other.id} label={other.title} />
        </div>
      )}
    </div>
  );
}

function EffectRow({ e, onCite }: { e: Effect; onCite: (c: Cite) => void }) {
  return (
    <li className="eff-row">
      <span className={`rw ${e.op === "read" ? "r" : "w"}`}>{opLetter(e.op)}</span>
      <code>{e.target}</code>
      {e.fields.length > 0 && <span className="dim"> {e.fields.join(", ")}</span>}{" "}
      <CiteLink
        cite={{ file: e.anchor.file, start: e.anchor.start_line, end: e.anchor.start_line }}
        onCite={onCite}
      />
    </li>
  );
}

export function DetailsTab({
  loader, regenerator = loader,
}: {
  loader: DetailLoader;
  regenerator?: DetailLoader;
}) {
  const nodeId = useStore((s) => s.selectedNodeId);
  const graph = useStore((s) => s.graph);
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [active, setActive] = useState<(Cite & { seq: number }) | null>(null);
  const [attempt, setAttempt] = useState(0);
  const traceId = graph?.trace.id;

  useEffect(() => {
    if (!nodeId || !traceId) return;
    let stale = false;
    setLoad({ state: "loading" });
    setActive(null);
    loader(traceId, nodeId).then(
      (detail) => !stale && setLoad({ state: "ok", detail, retrying: false }),
      (e) => !stale && setLoad({ state: "error", message: errText(e) }),
    );
    return () => {
      stale = true;
    };
  }, [traceId, nodeId, loader, attempt]);

  const retry = () => {
    if (!traceId || !nodeId) return;
    if (load.state !== "ok") return setAttempt((a) => a + 1);
    setLoad({ state: "ok", detail: load.detail, retrying: true });
    regenerator(traceId, nodeId).then(
      (detail) => setLoad({ state: "ok", detail, retrying: false }),
      (e) =>
        setLoad({
          state: "ok",
          detail: { ...load.detail, explain_error: errText(e) },
          retrying: false,
        }),
    );
  };

  const node = graph?.nodes.find((n) => n.id === nodeId);
  const detail = load.state === "ok" ? load.detail : null;
  const retrying = load.state === "ok" && load.retrying;
  const cited = useMemo<Cite[]>(
    () => [
      ...(detail?.explain?.steps ?? []).map((s) => ({ file: s.file, start: s.lines[0], end: s.lines[1] })),
      ...(detail?.effects ?? []).map((e) => ({
        file: e.anchor.file, start: e.anchor.start_line, end: e.anchor.end_line,
      })),
    ],
    [detail],
  );
  const onCite = (c: Cite) => setActive({ ...c, seq: (active?.seq ?? 0) + 1 });

  if (!node) {
    return <div className="empty-note">Select a node to see how it works.</div>;
  }
  const a0 = node.anchors[0];
  const explain = detail?.explain;
  return (
    <div className="details" data-testid="details-tab">
      <h2>{node.title}</h2>
      {node.summary && <p className="sum">{node.summary}</p>}
      {a0 && (
        <div className="code-name">
          {a0.file}:{a0.start_line} · {a0.symbol}
          {node.anchors.length > 1 && <span> +{node.anchors.length - 1}</span>}
        </div>
      )}
      {node.stale && <div className="stale-note">{STALE_WARNING}</div>}

      {load.state === "error" && (
        <div className="err-box">
          <span className="err">Could not load details: {load.message}</span>
          <button type="button" className="btn" onClick={retry}>Retry</button>
        </div>
      )}

      <h4>How it works</h4>
      {(load.state === "loading" || retrying) && <Skeleton lines={4} />}
      {explain && !retrying && (
        <ol className="steps">
          {explain.steps.map((s, i) => (
            <li key={i}>
              {s.text}{" "}
              <CiteLink cite={{ file: s.file, start: s.lines[0], end: s.lines[1] }} onCite={onCite} />
            </li>
          ))}
        </ol>
      )}
      {detail && !explain && !retrying && (
        <div className="err-box">
          <span className="err">
            {detail.explain_error
              ? `Could not explain this node: ${detail.explain_error}`
              : "No explanation yet."}
          </span>
          <button type="button" className="btn" onClick={retry}>Retry</button>
        </div>
      )}

      {(explain || load.state === "loading") && (
        <>
          <h4>Input / Output</h4>
          {explain ? (
            <div className="io">
              <IoBox kind="Input" side={explain.input} />
              <IoBox kind="Output" side={explain.output} />
            </div>
          ) : (
            <Skeleton lines={2} />
          )}
        </>
      )}

      {detail && (
        <>
          <h4>Data touched</h4>
          {detail.effects.length === 0 ? (
            <div className="dim">None.</div>
          ) : (
            <ul className="plain">
              {detail.effects.map((e, i) => (
                <EffectRow key={i} e={e} onCite={onCite} />
              ))}
            </ul>
          )}

          <h4>Calls</h4>
          {detail.calls.length === 0 ? (
            <div className="dim">None.</div>
          ) : (
            <ul className="plain calls">
              {detail.calls.map((c, i) => {
                const target = c.node_id ? graph?.nodes.find((n) => n.id === c.node_id) : undefined;
                return (
                  <li key={i}>
                    {target ? <NodeLink id={target.id} label={c.symbol} /> : <code>{c.symbol}</code>}
                  </li>
                );
              })}
            </ul>
          )}

          <h4>Code</h4>
          {detail.functions.length === 0 ? (
            <div className="dim">No code available.</div>
          ) : (
            <CodeView functions={detail.functions} cited={cited} active={active} />
          )}
        </>
      )}
      {load.state === "loading" && (
        <>
          <h4>Code</h4>
          <Skeleton lines={5} />
        </>
      )}
    </div>
  );
}
