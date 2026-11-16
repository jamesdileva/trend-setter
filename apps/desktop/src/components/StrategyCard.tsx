import { useCallback, useEffect, useState } from "react";
import type {
  PaperLoopStatus,
  StrategyConfigView,
  StrategyDecisionView,
} from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

const SIGNAL_LABELS: Record<string, string> = {
  buy: "BUY signal",
  sell: "SELL signal",
  hold: "HOLD — no action",
};

const SIGNAL_CLASSES: Record<string, string> = {
  buy: "state-running",
  sell: "state-crashed",
  hold: "state-stopped",
};

interface Draft {
  fast: string;
  slow: string;
  rsi: string;
  ceiling: string;
}

const DEFAULT_DRAFT: Draft = { fast: "20", slow: "50", rsi: "14", ceiling: "70" };

export function StrategyCard() {
  const api = getDesktopApi();
  const [config, setConfig] = useState<StrategyConfigView | null>(null);
  const [loop, setLoop] = useState<PaperLoopStatus | null>(null);
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT);
  const [decision, setDecision] = useState<StrategyDecisionView | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!api) {
      return;
    }
    let cancelled = false;
    void api
      .getStrategyCurrent()
      .then((response) => {
        if (cancelled || !response || typeof response.body !== "object" || response.body === null) {
          return;
        }
        const view = response.body as StrategyConfigView;
        setConfig(view);
        if (view.config) {
          setDraft({
            fast: String(view.config.fast_ema_period),
            slow: String(view.config.slow_ema_period),
            rsi: String(view.config.rsi_period),
            ceiling: String(view.config.rsi_entry_ceiling),
          });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [api]);

  // The automated loop's liveness: last decision, last evaluated candle.
  useEffect(() => {
    if (!api) {
      return;
    }
    const refresh = (): void => {
      void api
        .getPaperStatus()
        .then((response) => {
          if (response && typeof response.body === "object" && response.body !== null) {
            setLoop(response.body as PaperLoopStatus);
          }
        })
        .catch(() => undefined);
    };
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [api]);

  const handleSave = useCallback(async () => {
    if (!api) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const response = await api.saveStrategyConfig({
        product_id: config?.config?.product_id ?? "BTC-USD",
        timeframe: config?.config?.timeframe ?? "1h",
        fast_ema_period: Number(draft.fast),
        slow_ema_period: Number(draft.slow),
        rsi_period: Number(draft.rsi),
        rsi_entry_ceiling: Number(draft.ceiling),
      });
      const body = (response?.body ?? {}) as { status?: string; message?: string; version?: number };
      if (response?.status === 200) {
        setNotice({ kind: "ok", text: `Saved. The new settings apply from the next completed candle (version ${body.version ?? 1}).` });
        const refreshed = await api.getStrategyCurrent();
        if (refreshed && typeof refreshed.body === "object" && refreshed.body !== null) {
          setConfig(refreshed.body as StrategyConfigView);
        }
      } else {
        setNotice({ kind: "error", text: body.message ?? "The settings were rejected. Check the values." });
      }
    } catch {
      setNotice({ kind: "error", text: "The engine is not reachable yet. Wait for it to start and try again." });
    } finally {
      setBusy(false);
    }
  }, [api, config, draft]);

  const handleEvaluate = useCallback(async () => {
    if (!api) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const response = await api.evaluateStrategy({});
      const body = (response?.body ?? {}) as StrategyDecisionView;
      setDecision(body);
    } catch {
      setNotice({ kind: "error", text: "The engine is not reachable yet. Wait for it to start and try again." });
    } finally {
      setBusy(false);
    }
  }, [api]);

  const configured = config?.configured === true;

  return (
    <section className="card" aria-live="polite">
      <h2>Strategy (paper evaluation only — no orders)</h2>
      <p className="meta">
        The strategy watches for a moment when the short-term price trend crosses the long-term
        trend, and checks that the market isn't overheated before suggesting a buy.
      </p>
      <details className="strategy-help">
        <summary>What do these terms mean?</summary>
        <p>
          <b>Fast EMA</b> tracks the recent price trend over a small number of candles (default
          20). Think of it as a "quick reaction" line.
        </p>
        <p>
          <b>Slow EMA</b> tracks the longer-term trend over more candles (default 50). It reacts
          more slowly but is steadier.
        </p>
        <p>
          When the fast line <b>crosses above</b> the slow line, that suggests upward momentum —
          a possible buy. When it crosses below, that suggests downward momentum — a possible sell.
        </p>
        <p>
          <b>RSI</b> (Relative Strength Index) is a 0–100 score of whether the market is
          overheated. The entry ceiling (default 70) means "don't buy unless RSI is below this
          number" — a check that the market isn't in a buying frenzy.
        </p>
        <p>
          These are starting values, not recommendations. You can adjust them and see how the
          strategy responds.
        </p>
      </details>

      <div className="current-run">
        <h3>What's running right now</h3>
        {config?.configured && config.config ? (
          <>
            <p className="meta">
              Watching <b>{config.config.product_id}</b> on{" "}
              <b>{config.config.timeframe === "1h" ? "hourly" : config.config.timeframe}</b>{" "}
              candles — the engine checks the strategy automatically every time a candle
              completes.
            </p>
            <p className="meta">
              Fast EMA {config.config.fast_ema_period} · slow EMA {config.config.slow_ema_period} ·
              RSI {config.config.rsi_period}, buys only when RSI is below{" "}
              {config.config.rsi_entry_ceiling}.
            </p>
            <p className="meta">
              Automated checking:{" "}
              <b className={loop?.running ? "state-running" : "state-stopped"}>
                {loop?.running ? "active" : "waiting for candles"}
              </b>
              {loop?.last_processed_candle &&
                ` · last checked candle ${loop.last_processed_candle.replace("T", " ").slice(0, 16)} UTC`}
            </p>
            {loop?.last_decision && (
              <p className="meta">
                Last automated decision:{" "}
                <b>{SIGNAL_LABELS[loop.last_decision] ?? loop.last_decision}</b>
                {loop.last_decision_reason && ` (${loop.last_decision_reason.replace(/_/g, " ")})`}
                {loop.details?.last_error ? ` — problem: ${String(loop.details.last_error)}` : ""}
              </p>
            )}
            {config.recent_signals && config.recent_signals.length > 0 && (
              <details className="strategy-help">
                <summary>Recent automated decisions ({config.recent_signals.length})</summary>
                {config.recent_signals.slice(0, 8).map((signal) => (
                  <p className="meta" key={`${signal.candle_time}-${signal.decision}`}>
                    <b>{signal.decision.toUpperCase()}</b> on candle{" "}
                    {signal.candle_time.replace("T", " ").slice(0, 16)} UTC — {signal.explanation}
                  </p>
                ))}
              </details>
            )}
            {(config.recent_signals?.length ?? 0) === 0 && (
              <p className="meta">
                No automated decisions recorded yet — the engine records one every time a
                candle closes.
              </p>
            )}
          </>
        ) : (
          <p className="meta">
            No strategy is saved yet — the automated loop starts once you save settings below.
          </p>
        )}
      </div>

      <div className="strategy-fields">
        <label>
          Fast EMA period
          <input
            type="number"
            value={draft.fast}
            onChange={(event) => setDraft({ ...draft, fast: event.target.value })}
            min={2}
          />
        </label>
        <label>
          Slow EMA period
          <input
            type="number"
            value={draft.slow}
            onChange={(event) => setDraft({ ...draft, slow: event.target.value })}
            min={3}
          />
        </label>
        <label>
          RSI period
          <input
            type="number"
            value={draft.rsi}
            onChange={(event) => setDraft({ ...draft, rsi: event.target.value })}
            min={2}
          />
        </label>
        <label>
          RSI entry ceiling (0–100)
          <input
            type="number"
            value={draft.ceiling}
            onChange={(event) => setDraft({ ...draft, ceiling: event.target.value })}
          />
        </label>
      </div>

      <div className="controls">
        <button type="button" onClick={() => void handleSave()} disabled={busy}>
          Save &amp; apply
        </button>
        <button type="button" onClick={() => void handleEvaluate()} disabled={busy || !configured}>
          Evaluate now
        </button>
      </div>
      {!configured && (
        <p className="meta">Save a configuration first — evaluation needs one.</p>
      )}

      {decision && (
        <div className="decision">
          <p className={`state ${SIGNAL_CLASSES[decision.signal] ?? ""}`}>
            {SIGNAL_LABELS[decision.signal] ?? decision.signal}
          </p>
          <p className="meta">
            {decision.product_id} @ {decision.timeframe}
            {decision.candle_time ? ` · candle ${decision.candle_time.replace("T", " ").slice(0, 16)} UTC` : ""}
          </p>
          <p className="meta">{decision.explanation}</p>
          {decision.indicator_values && Object.keys(decision.indicator_values).length > 0 && (
            <p className="meta">
              Evidence:{" "}
              {Object.entries(decision.indicator_values)
                .map(([name, value]) => `${name}=${value}`)
                .join(", ")}
            </p>
          )}
        </div>
      )}

      {notice && (
        <p className={notice.kind === "ok" ? "meta" : "error"} role={notice.kind === "error" ? "alert" : undefined}>
          {notice.text}
        </p>
      )}
    </section>
  );
}
