import { useReactFlow } from "@xyflow/react";
import { CATEGORY_COLOR, CATEGORY_LABEL, type UiCategory } from "./effects/categories";
import { useStore, type PanelTab } from "./state/store";

const CATS = Object.keys(CATEGORY_LABEL) as UiCategory[];
const TABS: { id: PanelTab; label: string }[] = [
  { id: "details", label: "Details" },
  { id: "data", label: "Data touched" },
];

export function Toolbar() {
  const { fitView } = useReactFlow();
  const hidden = useStore((s) => s.hiddenCategories);
  const tab = useStore((s) => s.panelTab);
  const panelOpen = useStore((s) => s.panelOpen);
  const { expandAll, collapseAll, toggleCategory, showPanel, togglePanel } = useStore.getState();
  return (
    <div className="toolbar">
      <button type="button" className="btn" onClick={expandAll}>Expand all</button>
      <button type="button" className="btn" onClick={collapseAll}>Collapse all</button>
      <button type="button" className="btn" onClick={() => void fitView({ maxZoom: 1, duration: 400 })}>Fit</button>
      <span className="divider" />
      {CATS.map((c) => (
        <button
          key={c}
          type="button"
          className="btn cat"
          aria-pressed={!hidden.has(c)}
          style={{ ["--cat" as string]: CATEGORY_COLOR[c] }}
          onClick={() => toggleCategory(c)}
        >
          <i className="cat-dot" />
          {CATEGORY_LABEL[c]}
        </button>
      ))}
      <span className="sp" />
      {TABS.map((t) => {
        const on = panelOpen && tab === t.id;
        return (
          <button
            key={t.id}
            type="button"
            className="btn tab-toggle"
            aria-pressed={on}
            onClick={() => (on ? togglePanel() : showPanel(t.id))}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
