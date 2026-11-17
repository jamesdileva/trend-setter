# Sprint 16 — Strategy comparison: backtest ranking across strategy families

- **Roadmap sprint:** Post-roadmap (follows Sprint 15)
- **Status:** In progress
- **Date:** 2026-11-17

## Goal

Give the user a disciplined way to find a better strategy: import a year of history, add a
second strategy family with different failure modes, and rank candidates by out-of-sample
backtest performance against a buy-and-hold benchmark — while being explicit that
backtest rankings are candidates, not promises. Picking the winner stays a human decision.

## Scope

Files to create or change:

- `engine/src/trendbot/strategies/config.py` — `StrategyConfig` protocol (the shared config
  surface: product, timeframe, validate, require_valid, config_hash) and `DonchianConfig`.
- `engine/src/trendbot/strategies/donchian.py` (new) — Donchian-channel breakout strategy:
  BUY when the close exceeds the highest high of the prior `entry_lookback` candles; SELL
  when the close falls below the lowest low of the prior `exit_lookback` candles (turtle-style,
  exit channel shorter than entry channel). Registered as `donchian_breakout`.
- `engine/src/trendbot/strategies/registry.py` — register the Donchian strategy.
- `engine/src/trendbot/backtesting/engine.py` — config annotation loosened to the protocol.
- `engine/src/trendbot/application/backtest_service.py` — `strategy_name` parameter (default
  unchanged), `persist` flag (compare sweeps do not spam the runs table).
- `engine/src/trendbot/application/strategy_compare.py` (new) — `compare_strategies`: runs a
  SMALL grid per strategy family (6 EMA/RSI combos, 3 Donchian combos) over the same window
  with the same fee assumptions, computes a buy-and-hold benchmark row, ranks by
  out-of-sample net return, and attaches plain-language caveats (overfitting, trade-count
  strength).
- `engine/src/trendbot/api/app.py` + `schemas.py` — token-gated `POST /backtest/compare`.
- `apps/desktop` — "Compare strategies" section in the Backtest card: ranked table
  (full-window return, OOS return, OOS drawdown, OOS trades) with the benchmark row and
  caveats; nothing auto-applies the winner.
- Tests: `tests/test_donchian.py`, `tests/test_strategy_compare.py`, API endpoint test.
- Data: one year of hourly candles imported for BTC-USD and ETH-USD (8,755 each, two small
  known gaps) via the existing `import_history` tool.

Out of scope: parallel shadow-paper trading of multiple strategies (needs per-strategy paper
accounts — a later sprint), parameter optimization beyond the small grid, walk-forward
analysis, live auto-selection.

## Acceptance criteria

- [ ] Both strategy families backtest over the imported year with identical fee assumptions.
- [ ] The comparison ranks by out-of-sample net return and always shows the buy-and-hold
      benchmark and its own return for context.
- [ ] Results carry explicit plain-language caveats; low OOS trade counts are marked weak.
- [ ] Nothing in the compare path changes the active strategy or places orders.
- [ ] Donchian unit tests cover breakout entry, channel exit, insufficient history, and
      validation; compare tests cover ranking, benchmark presence, and determinism.

## Verification (fill in before closing)

- `engine`: `python -m pytest` → **432 passed** (12 Donchian, 6 compare, 3 endpoint tests
  added); `python -m ruff check src tests` → clean; `python -m mypy src` → clean (76 files).
- Desktop: `npx tsc --noEmit` clean; `npx vitest run` → 19 passed; renderer + main build OK.
- `python scripts/repo_checks.py` → OK.
- Data: 8,755 hourly candles per product imported (2025-11-17 → 2026-11-17); two small
  known gaps (2025-11-17 20:00-21:00, 2026-05-08 02:00-07:00 UTC).
- Live comparison run on real BTC-USD data (2026-11-17): buy-and-hold -32.0% over the year;
  every candidate lost less than the benchmark (best OOS: EMA 50/200 at -7.7%, only 3
  trades — marked weak evidence). No candidate was profitable; the ranking honestly
  reflects a bear year under 1%/side placeholder fees.

## Deviations & follow-ups

- Backtester window contract fixed during this sprint: strategies now evaluate on exactly
  `required_history` candles (matching the live paper loop) instead of the growing full
  prefix. This both fixes an O(n²) slowdown (full-year sweep: >5 min → ~15 s) and aligns
  backtest decisions with live behavior for recursive indicators.
- Backtest service gained a `persist` flag; comparison sweeps skip the runs table.
- Follow-up candidates: parallel shadow-paper trading of top candidates (per-strategy paper
  accounts), walk-forward validation, fee-sensitivity view (results are very sensitive to
  the 1%/side placeholder fee).

## Deviations & follow-ups

-
