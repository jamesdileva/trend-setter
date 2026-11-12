import { useCallback, useEffect, useState } from "react";
import type { EngineResponse } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

interface PaperStatus {
  warning: string;
  account_kind: string;
  mode: string;
  entries_allowed: boolean;
  cash: string;
  starting_balance: string;
  session_started_at: string | null;
  position: {
    product_id: string;
    size: string;
    side: string;
    average_entry_price: string | null;
  };
}

const MODE_LABELS: Record<string, string> = {
  normal: "Running",
  entries_paused: "Entries paused",
  stopped: "Stopped",
  emergency_stopped: "EMERGENCY STOP",
};

export function PaperCard() {
  const api = getDesktopApi();
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!api) {
      return;
    }
    void api
      .getPaperStatus()
      .then((response) => {
        if (response && typeof response.body === "object" && response.body !== null) {
          setStatus(response.body as PaperStatus);
        }
      })
      .catch(() => undefined);
  }, [api]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  const act = useCallback(
    async (path: string, body?: Record<string, unknown>) => {
      setBusy(true);
      setError(null);
      try {
        const response = (await api?.paperControl(path, body ?? {})) as EngineResponse | null;
        if (response && response.status !== 200) {
          const errBody = response.body as { message?: string };
          setError(errBody.message ?? "The action failed.");
        }
        refresh();
      } catch {
        setError("The engine is not reachable yet.");
      } finally {
        setBusy(false);
      }
    },
    [api, refresh],
  );

  const mode = status?.mode ?? "unknown";
  const emergency = mode === "emergency_stopped";

  return (
    <section className="card paper-card" aria-live="polite">
      <h2>
        Paper trading <span className="paper-badge">PAPER — simulated funds</span>
      </h2>
      <p className="meta">{status?.warning ?? "Paper trading uses simulated funds only."}</p>

      <div className="paper-stats">
        <MetricRow label="Mode" value={MODE_LABELS[mode] ?? mode} />
        <MetricRow label="Cash (simulated)" value={status?.cash ?? "—"} />
        <MetricRow
          label="Position"
          value={
            status
              ? `${status.position.side} ${status.position.size} ${status.position.product_id}`
              : "—"
          }
        />
        {status?.position.average_entry_price && (
          <MetricRow label="Avg entry" value={status.position.average_entry_price} />
        )}
        <MetricRow label="Session start" value={status?.session_started_at ?? "—"} />
      </div>

      {emergency && (
        <p className="error" role="alert">
          EMERGENCY STOP is active. Re-arm to resume.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="controls">
        <button type="button" onClick={() => void act("/paper/start")} disabled={busy}>
          Start / resume
        </button>
        <button type="button" onClick={() => void act("/paper/pause")} disabled={busy}>
          Pause entries
        </button>
        <button type="button" onClick={() => void act("/paper/stop")} disabled={busy}>
          Stop
        </button>
        <button
          type="button"
          className="danger"
          onClick={() => void act("/paper/emergency-stop")}
          disabled={busy}
        >
          Emergency stop
        </button>
        <button type="button" onClick={() => void act("/paper/reset")} disabled={busy}>
          Reset paper account
        </button>
      </div>
    </section>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <p className="meta">
      {label}: <b>{value}</b>
    </p>
  );
}
