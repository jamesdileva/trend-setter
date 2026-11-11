# Sprint 07 — Backtesting engine and evaluation UI

- **Roadmap sprint:** Sprint 7 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-11

## Goal

Replay strategies over stored historical candles with explicit, conservative assumptions and visible limitations: next-open fills, fees on both sides, slippage, increment rounding, no look-ahead, an out-of-sample split, persisted and exportable results — clearly labeled as simulations.

## Scope

Engine (`engine/`), per architecture.md §11 and implementation.md §10:

- `backtesting/assumptions.py` — `FeeAssumptions`: per-side fee and slippage (bps), base increment rounding. Defaults are deliberately conservative **placeholders** (fee 100 bps/side, slippage 10 bps/side) — real fee tiers are account-dependent and must not be treated as facts (architecture.md §10)
- `backtesting/engine.py` — `BacktestEngine`: decisions on candle *t* close execute at candle *t+1* **open** ± slippage (no intrabar sequencing, no look-ahead — the window ends at *t*); fees charged on entry and exit; base sizes rounded **down** to the increment; equity curve marked to close; trade ledger; force-close at end-of-data (labeled); metrics: net/gross return, max drawdown, trade count, win rate, avg win/loss, profit factor, exposure %, total fees, buy-and-hold benchmark
- `backtesting/results.py` — in-sample/out-of-sample split (configurable fraction, separate runs), JSON/CSV export
- Persistence: `BacktestRepository` (runs + trades into the Sprint 2 tables), `StrategyConfigRepository.get_or_create` (backtests must not change the user's active config)
- `application/backtest_service.py` — runs a backtest over the stored candle range, computes the OOS split, persists everything, returns a labeled result
- API: `POST /backtest/run`, `GET /backtest/runs` (token-gated; responses carry a simulation warning banner)
- Desktop: backtest card labeled **HISTORICAL SIMULATION** with the summary metrics

Documented candle-resolution limitations (architecture.md §11): fills happen at next-open only; intrabar stop/target sequencing is unknowable from candles; defaults are placeholders.

Out of scope: walk-forward optimization loops (documented follow-up), the full risk manager (Sprint 8 — backtests use fixed notional sizing for now), parameter-sweep UI.

## Acceptance criteria (roadmap Sprint 7 verification)

- [x] Hand-calculated small scenarios match expected output (losing trade with 1% fees: pnl −100.0000005, net −10%, max drawdown 10%, exposure 25%; winning trade without fees: +55.555555, net +5.5556%)
- [x] Fees reduce net results correctly on both sides (net < gross; fees total = entry + exit fees, asserted)
- [x] No future candle values leak into decisions (prefix-vs-extended run: recorded decisions on shared windows are identical)
- [x] Same inputs/config produce same results (three runs → identical frozen dataclass equality)
- [x] Out-of-sample period is separate from tuning period (70/30 chronological split; separate runs + metrics; never overlaps)
- [x] UI distinguishes historical simulation from paper/live activity (card + response banner: "HISTORICAL SIMULATION — not paper trading, not live")

## Verification

Commands and results (Python 3.14.3, Node 24.14.1):

- `python -m pytest` (in `engine/`) — **257 passed** (+18: hand-scenario engine tests, look-ahead/determinism, split/export, persistence, API endpoints)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 55 source files
- `npm run typecheck` / `npm test` (in `apps/desktop/`) — clean; 11 passed; build clean
- `python scripts/repo_checks.py` — OK: 141 files scanned
- Engine correctness check surfaced and fixed a real flaw: entries did not account for the fee against available cash (an unaffordable all-in entry could push simulated cash negative) — entries now require notional + fee in cash

## Deviations & follow-ups

- The full risk manager arrives in Sprint 8; backtests currently use fixed quote-notional sizing with an affordability check. Wiring the risk manager into the simulation is the natural follow-up.
- Walk-forward evaluation is a documented follow-up — the 70/30 split covers the roadmap's "out-of-sample or walk-forward" requirement for now.
- Entry sizing rounds the base size down to the product increment; partial-fill modeling is a placeholder (flat assumption) until Sprint 8's execution layer defines the shared interface.
- Fee/slippage defaults (100/10 bps) are conservative placeholders recorded on every run — the user's real fee tier must be configured before trusting live comparisons.
- Buy-and-hold benchmark uses first-to-last close over the run range.
