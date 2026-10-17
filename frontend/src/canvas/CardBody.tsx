import type { Effect, Node } from "../api/types";
import { CATEGORY_COLOR, opLetter, uiCategory } from "../effects/categories";

export type CardBodyProps = {
  node: Node;
  depth: number;
  chips: { shown: Effect[]; more: number };
  caret: string; // "" when the node cannot open
  // "card" is a leaf card. "header" is the title block of an open node (no chips).
  variant: "card" | "header";
  onChip?: (e: Effect) => void;
};

// Pure markup shared by the canvas card and the offscreen measurer, so both use the same CSS.
export function CardBody({ node, depth, chips, caret, variant, onChip }: CardBodyProps) {
  const level = Math.min(depth, 2);
  return (
    <div className={`node-card lvl-${level}${variant === "header" ? " is-header" : ""}`}>
      <div className="nc-title">
        {caret && <span className="caret">{caret}</span>}
        <span className="nc-name">{node.title}</span>
        {node.stale && (
          <span className="stale-dot" title="Code changed since this trace">
            code changed
          </span>
        )}
      </div>
      {node.summary && <div className="nc-summary">{node.summary}</div>}
      {variant === "card" && (chips.shown.length > 0 || chips.more > 0) && (
        <div className="chips">
          {chips.shown.map((e, i) => {
            const cat = uiCategory(e.category);
            return (
              <button
                key={i}
                type="button"
                className="chip nodrag"
                data-testid="chip"
                data-category={cat}
                style={{ ["--cat" as string]: CATEGORY_COLOR[cat] }}
                onClick={(ev) => {
                  ev.stopPropagation();
                  onChip?.(e);
                }}
              >
                <b>{opLetter(e.op)}</b>
                <span className="chip-target">{e.target}</span>
              </button>
            );
          })}
          {chips.more > 0 && <span className="more">+{chips.more}</span>}
        </div>
      )}
    </div>
  );
}
