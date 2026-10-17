import { useMemo } from "react";
import {
  CATEGORY_COLOR, CATEGORY_LABEL, opLetter, targetsOf, type Target, type UiCategory,
} from "../effects/categories";
import { useStore } from "../state/store";

export function DataTab() {
  const graph = useStore((s) => s.graph);
  const hidden = useStore((s) => s.hiddenCategories);
  const selected = useStore((s) => s.selectedTarget);
  const selectTarget = useStore((s) => s.selectTarget);
  const groups = useMemo(
    () => (graph ? targetsOf(graph, hidden) : new Map<UiCategory, Target[]>()),
    [graph, hidden],
  );
  const order = Object.keys(CATEGORY_LABEL) as UiCategory[];
  return (
    <div className="data-tab" data-testid="data-tab">
      <p className="sub">What this flow reads and writes. Click a row to light up the nodes.</p>
      {groups.size === 0 && <div className="dim">No data touched.</div>}
      {order.map((cat) => {
        const targets = groups.get(cat);
        if (!targets) return null;
        return (
          <section key={cat} data-category={cat}>
            <div className="cat-head" style={{ color: CATEGORY_COLOR[cat] }}>
              {CATEGORY_LABEL[cat]}
            </div>
            <div className="dt">
              {targets.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className="dt-row"
                  data-testid={`target-${t.key}`}
                  aria-pressed={selected === t.key}
                  onClick={() => selectTarget(selected === t.key ? null : t.key)}
                >
                  <span className="nm">{t.label}</span>
                  <span className="tags">
                    {t.tags.map((g, i) => (
                      <span className="ph" key={i}>
                        <b>{opLetter(g.op)}</b> {g.phaseTitle}
                      </span>
                    ))}
                  </span>
                </button>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
