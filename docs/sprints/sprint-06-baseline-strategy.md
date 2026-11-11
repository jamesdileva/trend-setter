# Sprint 06 — Baseline strategy and configuration

- **Roadmap sprint:** Sprint 6 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-11

## Goal

Implement the configurable EMA crossover + RSI strategy as a deterministic, independently tested module with versioned config, persisted reproducible signals, and UI controls — no order execution.

## Scope

Engine (`engine/`), per architecture.md §8 and implementation.md §8:

- `strategies/indicators/ema.py`, `strategies/indicators/rsi.py` — pure indicator functions over Decimal closes (float internally per architecture.md §7), documented warm-up: EMA seeds with an SMA at index `period-1`; RSI uses Wilder smoothing with a documented flat-series convention (RSI 50); leading `None`s until warm-up completes
- `strategies/decisions.py` — `SignalType` (BUY/SELL/HOLD), `StrategyDecision` (signal, product/timeframe, decision candle time, indicator evidence, reason code + plain explanation, strategy name/version, config hash), `StrategyPosition`
- `strategies/base.py` — `Strategy` ABC (`validate_config`, `required_history`, `evaluate(candles, config, position)`); strategies receive completed candles only
- `strategies/ema_rsi.py` — baseline: crossover semantics exactly as specified (bullish: `fast[t-1] <= slow[t-1]` and `fast[t] > slow[t]`), RSI entry filter (blocked buys explained, not silently dropped), optional RSI exit floor (disabled by default), duplicate-entry guard while in position, insufficient-history → explicit HOLD, exact hand-computed scenario fixtures
- `strategies/registry.py` — name → strategy lookup with plain-language unknown-strategy errors
- `strategies/config.py` — adds `rsi_exit_floor` (validated), `config_hash()` (canonical JSON → SHA-256) and the `ema_rsi_baseline` name
- Persistence: `StrategyConfigRepository` (versioned, active config), `SignalRepository` (idempotent per candle via new unique constraint — **migration 0002**), `CandleRepository.latest_complete_start` reuse
- `application/strategy_engine.py` — `StrategyEngine`: set/validate versioned config, evaluate from stored candles, persist decision; changes apply at the next completed-candle evaluation
- API: `POST /strategy/config`, `GET /strategy/current`, `POST /strategy/evaluate` (token-gated; decisions returned and persisted; no order endpoints)
- Desktop: strategy card — plain-language parameter controls, Save & apply, Evaluate now with BUY/SELL/HOLD display

Explicitly out of scope: order execution (Sprint 8), backtesting UI (Sprint 7), multi-instance portfolio of configs (single active config + per-request product/timeframe override; full instance management later).

## Acceptance criteria (roadmap Sprint 6 verification)

- [x] Indicator outputs match known reference fixtures (EMA seeds/smoothing and Wilder RSI hand-calculated, including flat→50 / monotonic→100/0 edge conventions)
- [x] Crossover fires only on actual transition, not every candle above/below (`detect_crossover` unit tests + sustained-trend scenario)
- [x] Insufficient history returns no signal (explicit HOLD `insufficient_history`)
- [x] Repeated evaluation is deterministic (identical dataclass equality)
- [x] Config validation rejects invalid periods (+ the new exit floor; fast≥slow, bounds, products, timeframes)
- [x] Signals are reproducible from stored candles and config (fresh engine over same state → identical decision; `uq_signal_per_candle` dedups repeated evaluation)
- [x] No strategy code can call exchange order methods (AST-based architecture guard over `strategies/`)
- [x] UI controls work with plain-language descriptions (StrategyCard: parameter fields, Save & apply, Evaluate now with evidence)

## Verification

Commands and results (Python 3.14.3, Node 24.14.1):

- `python -m pytest` (in `engine/`) — **239 passed** (+49: indicator fixtures, strategy scenarios, config hash/versioning, persistence + migration 0002, architecture guard, API endpoints)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 50 source files
- `npm run typecheck` / `npm test` (in `apps/desktop/`) — clean; 11 passed; build clean
- `python scripts/repo_checks.py` — OK: 131 files scanned
- Scenario fixtures are exact by construction: flat series keep EMAs exactly at the constant, so the crossover lands precisely on the crafted last candle (BUY with ceiling 97 where RSI computes to ≈96.9; SELL on the mirror; HOLD variants)
- CI from a clean checkout: run [43110515084](https://github.com/jamesdileva/trend-setter/actions/runs/43110515084) — **green** (repo hygiene, engine ruff+mypy+pytest, desktop typecheck+vitest)

## Deviations & follow-ups

- Migration 0002 revealed that **SQLite cannot ALTER-add constraints** — the migration uses Alembic batch mode (recreate-and-copy), per the Alembic SQLite docs. Recorded here as the pattern for future constraint migrations.
- The strategy evaluates a single active config with per-request product/timeframe overrides; full multi-instance config management (a portfolio of per-product configs) is deferred until the paper-trading sprint needs it.
- Signal rows store the granularity label (`ONE_HOUR`-style) to match the candles table; decisions carry the timeframe string.
- The duplicate-entry guard is strategy-level only; the authoritative position-aware enforcement arrives with the execution layer (Sprint 8), which also supplies real positions (the engine currently evaluates with a flat position).
- Architecture guard is text/AST-based on `strategies/` sources; the layering rules stay enforced by review + this tripwire.
