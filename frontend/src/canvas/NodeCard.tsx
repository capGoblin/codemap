import { Handle, Position } from "@xyflow/react";
import type { VisibleNode } from "../graph/visible";
import { chipsFor } from "../effects/categories";
import { EffectChip } from "../effects/EffectChip";
import { useStore } from "../state/store";

export type CardData = { vn: VisibleNode; faded: boolean; [k: string]: unknown };

export function opacityOf(vn: VisibleNode, faded: boolean): number {
  if (faded) return 0.3;
  return vn.dimmed ? 0.35 : 1;
}

export function NodeCard({ data, caret }: { data: CardData; caret?: string }) {
  const { vn, faded } = data;
  const hidden = useStore((s) => s.hiddenCategories);
  const error = useStore((s) => s.expandErrors.get(vn.id));
  const n = vn.node;
  const { shown, more } = chipsFor(n.effects, hidden);
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
      {error && <div className="err">{error}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
