import { useEffect, useState } from "react";
import type { EngineStatus, MarketDataStatus } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";
import { BacktestCard } from "../components/BacktestCard";
import { ConnectionCard } from "../components/ConnectionCard";
import { StrategyCard } from "../components/StrategyCard";

const STATE_LABELS: Record<EngineStatus["state"], string> = {
  stopped: "Engine stopped",
  starting: "Engine starting…",
  running: "Engine running",
  stopping: "Engine stopping…",
  crashed: "Engine error",
};

function feedLabel(status: MarketDataStatus | null): string {
  if (!status || !status.running) {
    return "Live feed not running";
  }
  const state = status.state ?? "unknown";
  const labels: Record<string, string> = {
    connected: "Live feed connected",
    connecting: "Live feed connecting…",
    reconnecting: "Live feed reconnecting…",
    stopped: "Live feed stopped",
    not_wired: "Live feed not wired in this build",
  };
  const lastComplete = Object.entries(status.last_complete ?? {});
  const newest = lastComplete.length > 0 ? ` · last candle ${lastComplete[0][1].slice(11, 16)} UTC` : "";
  return `${labels[state] ?? `Live feed: ${state}`}${newest}`;
}

export function App() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [marketStatus, setMarketStatus] = useState<MarketDataStatus | null>(null);
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
      void api
        .getMarketDataStatus()
        .then((response) => {
          if (response && typeof response.body === "object" && response.body !== null) {
            setMarketStatus(response.body as MarketDataStatus);
          } else {
            setMarketStatus(null);
          }
        })
        .catch(() => setMarketStatus(null));
    };
    refresh();
    const timer = setInterval(refresh, 5000);
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

      <section className="card" aria-live="polite">
        <h2>Market data</h2>
        <p className={`meta ${marketStatus?.state && marketStatus.state !== "connected" ? "warn" : ""}`}>
          {feedLabel(marketStatus)}
        </p>
        {marketStatus?.last_error && (
          <p className="error" role="alert">
            {marketStatus.last_error}
          </p>
        )}
      </section>

      <StrategyCard />

      <BacktestCard />

      <ConnectionCard />

      <footer className="app-footer">
        Paper mode by default. No real orders are placed. Live trading is a separate, deliberate
        workflow.
      </footer>
    </main>
  );
}
