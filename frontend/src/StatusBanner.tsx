import type { Trace } from "./api/types";

type Props = {
  status: Trace["status"];
  message: string | null;
  warning: string | null;
  // The message of the `finished` event. It holds the reason a trace is partial or failed.
  reason?: string | null;
};

export function StatusBanner({ status, message, warning, reason }: Props) {
  if (status === "running") {
    return (
      <div className="progress-strip" data-testid="progress-strip">
        {message ?? "Tracing..."}
      </div>
    );
  }
  if (status === "partial" || status === "failed") {
    return (
      <div className="banner-warn" data-testid="status-banner">
        Trace {status}.{reason || warning ? ` ${reason || warning}` : ""}
      </div>
    );
  }
  return null;
}
