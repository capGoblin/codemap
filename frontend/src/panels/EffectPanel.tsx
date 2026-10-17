import { opLetter, targetsOf } from "../effects/categories";
import { useStore } from "../state/store";

export function EffectPanel() {
  const graph = useStore((s) => s.graph);
  const key = useStore((s) => s.selectedTarget);
  const selectTarget = useStore((s) => s.selectTarget);
  const focusNode = useStore((s) => s.focusNode);
  if (!graph || !key) return null;
  // Hidden categories must not hide the target the user already selected.
  let target;
  for (const list of targetsOf(graph, new Set()).values()) {
    target = list.find((t) => t.key === key) ?? target;
  }
  if (!target) return null;
  const titles = new Map(graph.nodes.map((n) => [n.id, n.title]));
  return (
    <section className="panel effect-panel" data-testid="effect-panel">
      <header className="panel-head">
        <h2>{target.label}</h2>
        <button aria-label="Close effect panel" onClick={() => selectTarget(null)}>×</button>
      </header>
      <ul className="uses">
        {target.uses.map((u, i) => (
          <li key={i}>
            <button
              className="use"
              data-testid={`use-${u.nodeId}`}
              onClick={() => focusNode(u.nodeId)}
            >
              <span className="op">{opLetter(u.op)}</span> · {titles.get(u.nodeId)} ·{" "}
              {u.anchor.file}:{u.anchor.start_line}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
