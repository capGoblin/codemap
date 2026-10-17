import { useStore } from "./state/store";
import { expandChildren } from "./state/expand";

// One line per node whose lazy expand failed, with a Retry. Cards never carry error text, so their size stays fixed.
export function ExpandErrors() {
  const errors = useStore((s) => s.expandErrors);
  const nodes = useStore((s) => s.graph?.nodes);
  if (errors.size === 0) return null;
  return (
    <div className="banner-err" data-testid="expand-errors">
      {[...errors].map(([id, message]) => (
        <div key={id}>
          Could not open {nodes?.find((n) => n.id === id)?.title ?? id}: {message}{" "}
          <button type="button" className="btn" onClick={() => void expandChildren(id)}>
            Retry
          </button>
        </div>
      ))}
    </div>
  );
}
