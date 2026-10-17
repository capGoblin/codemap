import type { Effect } from "../api/types";
import { CATEGORY_COLOR, opLetter, targetKey, uiCategory } from "./categories";
import { useStore } from "../state/store";

export function EffectChip({ effect }: { effect: Effect }) {
  const selectTarget = useStore((s) => s.selectTarget);
  const selected = useStore((s) => s.selectedTarget);
  const key = targetKey(effect);
  return (
    <button
      type="button"
      className="chip nodrag"
      data-testid="chip"
      data-category={uiCategory(effect.category)}
      aria-pressed={selected === key}
      style={{ borderColor: CATEGORY_COLOR[uiCategory(effect.category)] }}
      onClick={(e) => {
        e.stopPropagation();
        selectTarget(selected === key ? null : key);
      }}
    >
      <b style={{ color: CATEGORY_COLOR[uiCategory(effect.category)] }}>{opLetter(effect.op)}</b>{" "}
      {effect.target}
    </button>
  );
}
