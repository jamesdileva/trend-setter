import { useCallback, useState } from "react";
import type { EngineResponse } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

interface CompareRow {
  strategy_name: string;
  params: string;
  full_net_return_pct: string;
  oos_net_return_pct: string;
  oos_max_drawdown_pct: string | null;
  oos_trade_count: number;
  oos_verdict: string;
}

interface CompareResult {
  status?: string;
  message?: string;
  product_id?: string;
  timeframe?: string;
  window?: { start?: string; end?: string; candles?: number; in_sample_fraction?: number };
  ranking?: CompareRow[];
  benchmark?: {
    strategy_name: string;
    params: string;
    full_net_return_pct: string;
    max_drawdown_pct: string;
    trade_count: number;
  } | null;
  caveats?: string[];
}

const STRATEGY_LABELS: Record<string, string> = {
  ema_rsi_baseline: "EMA crossover + RSI filter",
  donchian_breakout: "Donchian channel breakout",
  buy_and_hold_benchmark: "Buy & hold (benchmark)",
};

function returnClass(value: string): string {
  const number = Number(value);
  if (Number.isNaN(number)) return "";
  return number >= 0 ? "state-running" : "state-crashed";
}

/**
 * Compare candidate strategies on stored history, ranked by their
 * out-of-sample results. Advisory only — applying a strategy stays a
 * separate, explicit decision in the Strategy card.
 */
export function StrategyCompareCard() {
  const api = getDesktopApi();
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleCompare = useCallback(async () => {
    if (!api) return;
    setBusy(true);
    setError(null);
    try {
      const response = (await api.compareStrategies({
        product_id: "BTC-USD",
        timeframe: "1h",
      })) as EngineResponse | null;
      const body = (response?.body ?? {}) as CompareResult;
      if (response?.status === 200 && body.status === "comparison_complete") {
        setResult(body);
      } else {
        setError(body.message ?? "The comparison could not run. Check stored candle history.");
      }
    } catch {
      setError("The engine is not reachable yet. Wait for it to start and try again.");
    } finally {
      setBusy(false);
    }
  }, [api]);

  return (
    <section className="card" aria-live="polite">
      <h2>Compare strategies</h2>
      <p className="meta">
        Runs a few candidate strategies over the same stored history with the same fee
        assumptions, then ranks them by how they did on the <b>final 30% of candles</b> —
        data the parameters were not chosen on. A buy-and-hold benchmark shows what doing
        nothing would have done.
      </p>
      <div className="controls">
        <button type="button" onClick={() => void handleCompare()} disabled={busy}>
          {busy ? "Comparing…" : "Compare strategies (BTC-USD @ 1h)"}
        </button>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result?.benchmark && (
        <p className="meta">
          <b>{STRATEGY_LABELS[result.benchmark.strategy_name] ?? result.benchmark.strategy_name}</b>{" "}
          over this window:{" "}
          <b className={returnClass(result.benchmark.full_net_return_pct)}>
            {Number(result.benchmark.full_net_return_pct).toFixed(1)}%
          </b>{" "}
          (max drawdown {Number(result.benchmark.max_drawdown_pct).toFixed(1)}%)
        </p>
      )}

      {result?.ranking && (
        <div className="decision">
          {result.ranking.map((row, index) => (
            <div className="compare-row" key={`${row.strategy_name}-${row.params}`}>
              <p className="meta">
                <b>#{index + 1}</b>{" "}
                {STRATEGY_LABELS[row.strategy_name] ?? row.strategy_name} —{" "}
                <span className="meta">{row.params}</span>
              </p>
              <p className="meta">
                Full window: {Number(row.full_net_return_pct).toFixed(1)}% · Out-of-sample:{" "}
                <b className={returnClass(row.oos_net_return_pct)}>
                  {Number(row.oos_net_return_pct).toFixed(1)}%
                </b>{" "}
                · {row.oos_trade_count} OOS trades
                {row.oos_max_drawdown_pct &&
                  ` · OOS max drawdown ${Number(row.oos_max_drawdown_pct).toFixed(1)}%`}
              </p>
              <p className="meta">{row.oos_verdict}</p>
            </div>
          ))}
        </div>
      )}

      {result?.caveats && (
        <details className="strategy-help">
          <summary>Why the winner might not win (read this)</summary>
          {result.caveats.map((caveat) => (
            <p className="meta" key={caveat.slice(0, 32)}>
              {caveat}
            </p>
          ))}
          <p className="meta">
            Nothing here changes your strategy automatically. If one of these looks good,
            set it in the Strategy card and let the paper loop verify it on live data.
          </p>
        </details>
      )}
    </section>
  );
}
