import { useCallback, useState } from "react";
import type { EngineResponse } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

interface BacktestSummary {
  run_id?: number;
  result?: {
    net_return_pct?: string;
    gross_return_pct?: string;
    max_drawdown_pct?: string;
    trade_count?: number;
    win_rate_pct?: string | null;
    total_fees_quote?: string;
    benchmark_return_pct?: string;
  };
  out_of_sample?: {
    in_sample?: { net_return_pct?: string; trade_count?: number };
    out_of_sample?: { net_return_pct?: string; trade_count?: number };
  };
  message?: string;
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <p className="meta">
      {label}: <b>{value}</b>
    </p>
  );
}

export function BacktestCard() {
  const api = getDesktopApi();
  const [summary, setSummary] = useState<BacktestSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleRun = useCallback(async () => {
    if (!api) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = (await api.runBacktest({
        product_id: "BTC-USD",
        timeframe: "1h",
      })) as EngineResponse | null;
      const body = (response?.body ?? {}) as BacktestSummary;
      if (response?.status === 200) {
        setSummary(body);
      } else {
        setError(body.message ?? "The simulation could not run. Check stored candle history.");
      }
    } catch {
      setError("The engine is not reachable yet. Wait for it to start and try again.");
    } finally {
      setBusy(false);
    }
  }, [api]);

  const result = summary?.result;

  return (
    <section className="card" aria-live="polite">
      <h2>Historical simulation</h2>
      <p className="meta">
        Replays the baseline strategy over stored candles with placeholder fees and slippage.
        This is a <b>historical simulation</b> — not paper trading, not live, and not a
        prediction. Backtests are estimates with candle-resolution limits.
      </p>
      <div className="controls">
        <button type="button" onClick={() => void handleRun()} disabled={busy}>
          {busy ? "Running…" : "Run simulation (BTC-USD @ 1h)"}
        </button>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="decision">
          <MetricRow label="Net return" value={`${result.net_return_pct ?? "?"}%`} />
          <MetricRow label="Gross return (before fees)" value={`${result.gross_return_pct ?? "?"}%`} />
          <MetricRow label="Max drawdown" value={`${result.max_drawdown_pct ?? "?"}%`} />
          <MetricRow label="Trades" value={String(result.trade_count ?? 0)} />
          {result.win_rate_pct && <MetricRow label="Win rate" value={`${result.win_rate_pct}%`} />}
          <MetricRow label="Total fees" value={result.total_fees_quote ?? "?"} />
          <MetricRow label="Buy-and-hold benchmark" value={`${result.benchmark_return_pct ?? "?"}%`} />
          {summary?.out_of_sample && (
            <>
              <MetricRow
                label="In-sample net (tuning period)"
                value={`${summary.out_of_sample.in_sample?.net_return_pct ?? "?"}% (${summary.out_of_sample.in_sample?.trade_count ?? 0} trades)`}
              />
              <MetricRow
                label="Out-of-sample net (validation period)"
                value={`${summary.out_of_sample.out_of_sample?.net_return_pct ?? "?"}% (${summary.out_of_sample.out_of_sample?.trade_count ?? 0} trades)`}
              />
            </>
          )}
        </div>
      )}
    </section>
  );
}
