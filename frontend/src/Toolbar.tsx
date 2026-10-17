import { CATEGORY_COLOR, CATEGORY_LABEL, type UiCategory } from "./effects/categories";
import { useStore } from "./state/store";

const CATS = Object.keys(CATEGORY_LABEL) as UiCategory[];

export function Toolbar() {
  const hidden = useStore((s) => s.hiddenCategories);
  const { expandAll, collapseAll, toggleCategory, requestFit } = useStore.getState();
  return (
    <div className="toolbar">
      <button type="button" onClick={expandAll}>Expand all</button>
      <button type="button" onClick={collapseAll}>Collapse all</button>
      <button type="button" onClick={requestFit}>Fit</button>
      <span className="sep" />
      {CATS.map((c) => (
        <button
          key={c}
          type="button"
          className="cat"
          aria-pressed={!hidden.has(c)}
          style={{ borderLeftColor: CATEGORY_COLOR[c] }}
          onClick={() => toggleCategory(c)}
        >
          {CATEGORY_LABEL[c]}
        </button>
      ))}
    </div>
  );
}
