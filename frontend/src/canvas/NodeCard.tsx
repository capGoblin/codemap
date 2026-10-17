import { Handle, Position } from "@xyflow/react";
import type { VisibleNode } from "../graph/visible";
import { chipsFor } from "../effects/categories";
import { EffectChip } from "../effects/EffectChip";
import { useStore } from "../state/store";
import { expandPhase } from "../state/expand";

export type CardData = { vn: VisibleNode; faded: boolean; [k: string]: unknown };

export function opacityOf(vn: VisibleNode, faded: boolean): number {
  if (faded) return 0.3;
  return vn.dimmed ? 0.35 : 1;
}

export function NodeCard({ data, caret }: { data: CardData; caret?: string }) {
  const { vn, faded } = data;
  const hidden = useStore((s) => s.hiddenCategories);
  const error = useStore((s) => s.expandErrors.get(vn.id));
  const expanding = useStore((s) => s.expanding.has(vn.id));
  const eager = useStore((s) => s.graph?.trace.mode !== "lazy");
  const hasChildren = useStore((s) => s.graph?.nodes.some((x) => x.parent_id === vn.id) ?? false);
  const n = vn.node;
  const { shown, more } = chipsFor(n.effects, hidden);
  const unavailable = n.warnings.find((w) => w.startsWith("steps unavailable"));
  return (
    <div
      className={`card ${vn.kind}${vn.open ? " open" : ""}`}
      data-testid={`node-${vn.id}`}
      style={{ opacity: opacityOf(vn, faded) }}
    >
      <Handle type="target" position={Position.Left} />
      <div className="card-title">
        {caret && <span className="caret">{caret}</span>}
        {n.title}
      </div>
      <div className="card-io">
        {n.input} → {n.output}
      </div>
      <div className="chips">
        {shown.map((e, i) => (
          <EffectChip key={i} effect={e} />
        ))}
        {more > 0 && <span className="more">+{more}</span>}
      </div>
      {n.stale && <div className="stale">code changed</div>}
      {expanding && <span className="spinner" role="status" aria-label="Expanding" />}
      {error && !expanding && (
        <div className="err">
          {error}{" "}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              void expandPhase(vn.id);
            }}
          >
            Retry
          </button>
        </div>
      )}
      {vn.kind === "phase" && vn.open && eager && !hasChildren && !expanding && !error && (
        <div className="empty">
          {unavailable ?? "no steps"}
          {unavailable && (
            <>
              {" "}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void expandPhase(vn.id);
                }}
              >
                Retry
              </button>
            </>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
