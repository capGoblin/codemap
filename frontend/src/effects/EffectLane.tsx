import { useMemo, useState } from "react";
import {
  CATEGORY_COLOR, CATEGORY_LABEL, opLetter, targetsOf, type Target, type UiCategory,
} from "./categories";
import { useStore } from "../state/store";

export function EffectLane() {
  const graph = useStore((s) => s.graph);
  const hidden = useStore((s) => s.hiddenCategories);
  const selected = useStore((s) => s.selectedTarget);
  const selectTarget = useStore((s) => s.selectTarget);
  const [collapsed, setCollapsed] = useState(false);
  const columns = useMemo(() => (graph ? targetsOf(graph, hidden) : new Map<UiCategory, Target[]>()), [graph, hidden]);
  const titles = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n.title])), [graph]);

  return (
    <div className={`lane${collapsed ? " collapsed" : ""}`} data-testid="effect-lane">
      <button
        className="lane-toggle"
        aria-label="Toggle effect lane"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((c) => !c)}
      >
        Effects {collapsed ? "▴" : "▾"}
      </button>
      {!collapsed && (
        <div className="lane-cols">
          {[...columns.entries()].map(([cat, targets]) => (
            <div className="lane-col" key={cat} style={{ borderTopColor: CATEGORY_COLOR[cat] }}>
              <div className="lane-col-title">{CATEGORY_LABEL[cat]}</div>
              {targets.map((t) => (
                <button
                  key={t.key}
                  className="target-card"
                  data-testid={`target-${t.key}`}
                  aria-pressed={selected === t.key}
                  onClick={() => selectTarget(selected === t.key ? null : t.key)}
                >
                  <div className="target-label">{t.label}</div>
                  {t.uses.map((u, i) => (
                    <div className="target-use" key={i}>
                      {opLetter(u.op)}
                      {u.fields.length > 0 && ` ${u.fields.join(", ")}`} · {titles.get(u.nodeId)}
                    </div>
                  ))}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
