# Sprint 09 — Paper trading

- **Roadmap sprint:** Sprint 9 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-12

## Goal

Run the real market-data → strategy → risk → execution pipeline with simulated funds only: a persisted paper account (isolated from any Coinbase balance), next-open simulated fills with the same fee/slippage assumptions as the backtester, trading controls wired, restart recovery, and a visually unmistakable paper UI.

## Scope

Engine (`engine/`), per architecture.md §12 and implementation.md §10:

- `paper/account.py` — `PaperAccount`: persisted isolated cash (`app_settings`), every event appended to `balance_snapshots` with `account_kind="paper"` (never exchange balances), session start marker, reset (explicit `confirm=True` required) and JSON export
- `paper/engine.py` — `PaperTradingEngine`: polls completed candles, fills pending orders at **next-open** (same model as the backtester — consistent fees/slippage), evaluates the Sprint 6 strategy per completed candle, gates entries through the Sprint 8 `RiskManager` (stale gate, drawdown, cooldown, caps, kill switch), persists durable intents, applies fills idempotently, records paper equity to `balance_snapshots`, adopts the `TradingController` mode, and restarts safely: in-flight intents are canceled (paper fills apply at fill time, so persisted positions/cash already reflect every applied fill) and state is adopted from storage
- Guards: the paper package never imports the real Coinbase adapter (architecture-guard test); decisions during `entries_paused` are suppressed but exit management continues
- API: `POST /paper/start`, `POST /paper/pause`, `POST /paper/stop`, `POST /paper/emergency-stop`, `POST /paper/reset` (confirm required), `GET /paper/status` — all token-gated, every response carrying the paper banner
- Desktop: paper card — balances, position, session performance, controls, permanent PAPER labeling

Out of scope: live submission (Sprint 10), protective order types (Sprint 10), multi-product paper portfolios (single product this sprint), equity-curve charting UI (later polish sprint).

## Acceptance criteria (roadmap Sprint 9 verification)

- [x] No Coinbase order endpoint is called in paper mode (paper uses the fake adapter exclusively; an AST-based guard proves `trendbot/paper/` never imports the real client)
- [x] Paper balances are never shown as exchange balances (all snapshots `account_kind="paper"`; every response carries the PAPER TRADING banner)
- [x] Fees and simulated fills are applied consistently (same `FeeAssumptions` model as the backtester; next-open fills; entry fee 5.00 on 500 notional asserted exactly)
- [x] State survives app restart (cash, positions, and trading mode persist; a fresh engine adopts the persisted state — cash 492.475 and position 2.5 carried across)
- [x] Pause entries does not silently abandon protective management (bearish cross while paused → exit fires and fills)
- [x] Paper mode remains selected after restart unless the user changes it explicitly (mode persisted in `app_settings`, tested across engine instances)

## Verification

Commands and results (Python 3.14.3, Node 24.14.1):

- `python -m pytest` (in `engine/`) — **279 passed** (+45: paper loop with next-open fills, fee math to the cent — entry 1000 − 502.5 − 5.025 = 492.475, exit restores 739.975 — pause-exits-continue, restart adoption, isolation guards, reset confirmation, export)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 69 source files
- `npm run typecheck` / `npm test` (in `apps/desktop/`) — clean; 11 passed; build clean
- `python scripts/repo_checks.py` — OK: 163 files scanned
- CI from a clean checkout: run [43289616451](https://github.com/jamesdileva/trend-setter/actions/runs/43289616451) — **green** (repo hygiene, engine ruff+mypy+pytest, desktop typecheck+vitest)

## Deviations & follow-ups

- Paper fills are applied **at fill time** (not deferred), so persisted positions/cash always reflect every applied fill; the restart policy cancels in-flight intents and adopts persisted state — the safe direction, documented in `PaperTradingEngine._recover`.
- The engine currently evaluates the config from its constructor; a follow-up can re-read the active config per candle so config changes apply mid-session (the strategy engine already supports it).
- Equity snapshots mark to close at the candle's bucket end — intrabar equity is not modeled (consistent with the backtester).
- Single-product paper session this sprint; multi-product sessions need per-product engine instances (documented follow-up).
- The real Coinbase fee tier must replace the placeholder assumptions before comparing paper results to live expectations (same note as Sprint 7).
