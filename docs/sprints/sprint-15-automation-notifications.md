# Sprint 15 — Wire the trading loop, 1h candle rollup, current-run UI, email alerts

- **Roadmap sprint:** Post-roadmap (follows Sprint 14; recorded here because the roadmap is complete)
- **Status:** In progress
- **Date:** 2026-11-16

## Goal

Make the engine actually trade on its own: wire the built-but-unconnected paper pipeline into the
app's startup, give it the candles it needs (derived 1h), make the running strategy visible in the
UI, and notify the user by email when it acts or when the engine is in trouble.

## Investigation findings (the reason for this sprint)

The user reported days of running with zero paper trades. Findings (2026-11-16, `engine.db`):

1. **Root cause — the paper trading pipeline is never started.** `PaperTradingEngine`
   (evaluate → risk gate → order intent → fill → equity) is referenced nowhere outside its own
   module; `create_app` starts only the market-data feed. `/strategy/evaluate` is manual-only.
   `signals` has exactly one row (the 2026-11-12 smoke test); `order_intents`/`fills`/`positions`
   are empty; zero paper events in 26,500 `engine_events`.
2. **The active config (saved 2026-11-15) uses `1h`, but only `FIVE_MINUTE` candles are stored.**
   Live ingestion never aggregates, so the 1h config has no data to evaluate (aggregation helpers
   exist from Sprint 4 but were only used by the history importer).
3. **The WS feed is chronically unstable on this machine** (26,468 gap detections, 14 disconnects,
   DNS failures and handshake timeouts in 4 days). Candles still arrive via reconnect + backfill.
   Relevant to alerting: engine-problem emails must be rate-limited.

## Scope

Files to create or change:

- `engine/src/trendbot/market_data/rollup.py` — `HourlyRollupService`: derive complete `ONE_HOUR`
  candles from complete `FIVE_MINUTE` candles via `aggregate_candles`; store only fully complete
  hours (upsert is conflict-nothing, so incomplete hours must not be stored). Runs every loop
  cycle; catches up after backfills (max 48 hours per cycle).
- `engine/src/trendbot/paper/runner.py` — `PaperLoopRunner`: asyncio task that (a) runs the hourly
  rollup, (b) reads the active strategy config and (re)builds a `PaperTradingEngine` whenever the
  config hash changes (state persists in the DB; `recover()` adopts it), (c) calls
  `process_once()` every `poll_seconds`. No active config → idles (rollup still runs).
- `engine/src/trendbot/notifications/__init__.py` — `NotificationService`: SMTP email (SSL or
  STARTTLS), non-secret settings in `app_settings` (JSON), password in the OS credential store via
  `SecretStore`; `order_filled()` (always sent) and `problem()` (rate-limited: same key max once
  per 30 min, max 5/hour); all sends best-effort and never raise into trading code.
- `engine/src/trendbot/paper/engine.py` — optional `notifier` dependency; notify on entry/exit
  fills with a plain-language message; `PaperStatus` gains `last_processed_candle`.
- `engine/src/trendbot/market_data/live_feed.py` — optional `notifier`; rate-limited
  `problem("ws_disconnected", …)` at the disconnect recording point.
- `engine/src/trendbot/api/app.py` — lifespan starts the paper loop task (factory param, default
  None so existing tests are unaffected); `/paper/status` merges loop liveness
  (`last_processed_candle`, decision); new token-gated endpoints `GET/POST /notifications/email`
  and `POST /notifications/email/test` (password write-only, never returned).
- `engine/src/trendbot/main.py` — construct `NotificationService`, `HourlyRollupService`,
  `PaperLoopRunner`; pass the loop factory and notifier (feed + engine) into `create_app`.
- `apps/desktop/src/components/StrategyCard.tsx` — "Current run" panel: active config (read-only,
  plain language), loop state, last decision + reason + candle time, recent decisions.
- `apps/desktop/src/components/NotificationsCard.tsx` (new) + `types/electron.d.ts` +
  `electron/preload.ts` + `electron/main.ts` — notification settings UI and IPC.
- `docs/risk-register.md` — feed-instability observation.
- Tests: `tests/test_rollup.py`, `tests/test_paper_runner.py`, `tests/test_notifications.py`,
  app.py endpoint tests, paper-engine notify test.

Out of scope: live-loop wiring (live execution loop is a later roadmap item — the notifier hook
is designed so live fills call the same `order_filled`), push/SMS channels, HTML emails, daily
summary digest (declined for now), VPS.

## Acceptance criteria

- [ ] With the engine running and paper mode active, a fresh BUY/SELL crossover on the active
      config's timeframe produces a signal row, an order intent, and a paper fill — automatically.
- [ ] Changing strategy settings in the UI takes effect without restarting the engine.
- [ ] A 1h config evaluates successfully (1h candles derived from the 5m feed).
- [ ] The dashboard shows the running strategy, loop liveness, and the last automated decision.
- [ ] A fill triggers an email (when configured); engine problems trigger rate-limited emails;
      a wrong SMTP password/host produces a plain-language error in the test button, never a crash.
- [ ] SMTP password lives only in the OS credential store; repo checks stay green.
- [ ] Live trading remains force-disarmed on restart (R-06 untouched); paper auto-resumes only
      when its persisted mode says so.

## Verification (fill in before closing)

- `engine`: `python -m pytest` → **411 passed** (379 prior + 6 rollup + 16 notifications
  + 6 runner + 4 API endpoint tests); `python -m ruff check src tests` → clean.
- Desktop: `npx tsc --noEmit` clean; `npx vitest run` → 19 passed; renderer + main build OK.
- `python scripts/repo_checks.py` → OK (232 files, no secrets).
- Acceptance path covered by tests: crossover → signal row → order intent → paper fill →
  notification email (`test_paper_runner.py::TestAutomatedTrade`); 1h config evaluating
  derived candles (`TestRollupIntegration`); config change rebuild (`TestRunnerLifecycle`);
  rate-limited problem alerts and masked password endpoints (`test_notifications.py`,
  `test_api.py::TestNotificationsEndpoints`).
- Live verification on the operator's machine: packaged build run with the operator's real
  DB (2,300+ 5m candles) — 1h candles derived, loop active, decisions recorded.

## Deviations & follow-ups

-
