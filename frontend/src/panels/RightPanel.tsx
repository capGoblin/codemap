import { useCallback } from "react";
import type { DetailLoader } from "../api/types";
import { PANEL_MIN_WIDTH, useStore, type PanelTab } from "../state/store";
import { DataTab } from "./DataTab";
import { DetailsTab } from "./DetailsTab";

const TABS: { id: PanelTab; label: string }[] = [
  { id: "details", label: "Details" },
  { id: "data", label: "Data touched" },
];

export function RightPanel({
  loader, regenerator,
}: {
  loader?: DetailLoader;
  regenerator?: DetailLoader;
}) {
  const open = useStore((s) => s.panelOpen);
  const tab = useStore((s) => s.panelTab);
  const width = useStore((s) => s.panelWidth);
  const { showPanel, togglePanel, setPanelWidth } = useStore.getState();

  const startResize = useCallback(
    (ev: React.MouseEvent) => {
      ev.preventDefault();
      const max = Math.floor(window.innerWidth * 0.7);
      const move = (e: MouseEvent) =>
        setPanelWidth(Math.min(max, Math.max(PANEL_MIN_WIDTH, window.innerWidth - e.clientX)));
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    },
    [setPanelWidth],
  );

  if (!open) return null;
  return (
    <aside className="right-panel" style={{ width }} data-testid="right-panel">
      <div
        className="resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
        onMouseDown={startResize}
      />
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            className={tab === t.id ? "on" : ""}
            aria-selected={tab === t.id}
            onClick={() => showPanel(t.id)}
          >
            {t.label}
          </button>
        ))}
        <span className="sp" />
        <button type="button" className="collapse" aria-label="Collapse panel" onClick={togglePanel}>
          &raquo;
        </button>
      </div>
      <div className="panel-body">
        {tab === "details" ? (
          loader ? (
            <DetailsTab loader={loader} {...(regenerator ? { regenerator } : {})} />
          ) : (
            <div className="empty-note">No server connected.</div>
          )
        ) : (
          <DataTab />
        )}
      </div>
    </aside>
  );
}
