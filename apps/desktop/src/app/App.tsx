import { useEffect, useState } from "react";
import type { EngineStatus } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

const STATE_LABELS: Record<EngineStatus["state"], string> = {
  stopped: "Engine stopped",
  starting: "Engine starting…",
  running: "Engine running",
  stopping: "Engine stopping…",
  crashed: "Engine error",
};

export function App() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const api = getDesktopApi();

  useEffect(() => {
    if (!api) {
      return;
    }
    const refresh = (): void => {
      void api
        .getEngineStatus()
        .then((next) => setStatus(next))
        .catch(() => setStatus(null));
    };
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [api]);

  const state: EngineStatus["state"] = status?.state ?? "stopped";

  return (
    <main className="app">
      <header className="app-header">
        <span className="mode-badge">PAPER</span>
        <h1>trend-setter</h1>
      </header>

      <section className="card" aria-live="polite">
        <h2>Engine</h2>
        <p className={`state state-${state}`}>{STATE_LABELS[state]}</p>
        {status?.health ? (
          <p className="meta">
            Engine v{status.health.engine_version} · last health check ok
          </p>
        ) : (
          <p className="meta">Waiting for the engine…</p>
        )}
        {status?.lastError && (
          <p className="error" role="alert">
            {status.lastError}
          </p>
        )}
        <div className="controls">
          <button
            type="button"
            onClick={() => void api?.startEngine()}
            disabled={state === "running" || state === "starting"}
          >
            Start engine
          </button>
          <button
            type="button"
            onClick={() => void api?.stopEngine()}
            disabled={state === "stopped" || state === "stopping"}
          >
            Stop engine
          </button>
        </div>
      </section>

      <footer className="app-footer">
        Paper mode by default. No real orders are placed. Live trading is a separate, deliberate
        workflow.
      </footer>
    </main>
  );
}
