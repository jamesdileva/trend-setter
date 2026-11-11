# Sprint 04 — Historical market data and candle correctness

- **Roadmap sprint:** Sprint 4 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-11

## Goal

Reliable historical data ingestion: windowed Coinbase candle fetching (authenticated or public), validation, deduplication, gap detection, and deterministic aggregation — landing validated candles in the Sprint 2 tables.

## Scope

Engine (`engine/`), per architecture.md §7 and implementation.md §7:

- `src/trendbot/market_data/granularity.py` — verified Coinbase granularity labels ↔ seconds; roadmap timeframe mapping (1m/5m/15m/1h/4h — all native per Sprint 0); UTC bucket alignment
- `src/trendbot/market_data/aggregate.py` — deterministic multi-bucket aggregation (open = first, high = max, low = min, close = last, volume = sum; completeness = full bucket coverage) as the documented fallback for non-native combinations
- `src/trendbot/market_data/gaps.py` — missing-interval detection collapsed into `[start, end)` ranges
- `src/trendbot/exchange/backoff.py` — bounded exponential backoff with jitter, honoring `Retry-After` (Sprint 0 verified guidance)
- `src/trendbot/exchange/coinbase_rest.py` — extends the client: `get_candles` (authenticated, view scope) and `fetch_public_candles` (unauthenticated `/market/...` family — works without any API key); `CandlePage` result with quarantined-invalid accounting; `RateLimitedError` carrying `Retry-After`
- `src/trendbot/market_data/importer.py` — `CandleImporter.import_history()`: 350-bucket windowing, per-window deduplicated upserts, invalid-candle quarantine (rejected + counted, never stored), gap detection over the stored range, progress callback, `ImportSummary`
- `src/trendbot/tools/import_history.py` — operator CLI (public data when no credential is connected; authenticated when it is). The nontechnical-user import flow arrives with the backtest sprint UI
- `CandleRepository.latest_start()` — newest stored candle per product/timeframe (freshness query for Sprint 5's stale gate)

Out of scope: live WebSocket feed (Sprint 5), strategy consumption, import UI (Sprint 7), quarantine table (rejections are counted + event-logged; a table can be added if the audit need appears).

## Acceptance criteria (roadmap Sprint 4 verification)

- [x] Known fixture data imports with exact expected row counts (single- and multi-window: 48 hourly + 700 one-minute across two windows)
- [x] Repeated import does not duplicate candles (second run: 0 new, 48 duplicates — verified offline **and against the live API**)
- [x] Missing intervals are identified (consecutive + isolated gaps collapsed into ranges)
- [x] Aggregated candles match deterministic test fixtures (hand-calculated 1h→4h; partial groups marked incomplete; stored with `source=local_aggregated`)
- [x] Invalid candle data is rejected/quarantined (unparseable + OHLCV-violating entries counted, never stored, bucket reported missing)
- [x] Rate-limit responses back off without crashing (bounded 5 attempts, `Retry-After` honored, network errors retried)

## Verification

Commands and results (Python 3.14.3):

- `python -m pytest` (in `engine/`) — **159 passed** (+36: granularity/aggregation/gap fixtures, candle fetch params/parsing/quarantine, backoff behavior, end-to-end import)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 36 source files
- `python scripts/repo_checks.py` — OK: 104 files scanned
- Desktop suite unchanged and green (11 tests)

**Live public-API verification** (read-only, no credentials, nothing trading-related): `python -m trendbot.tools.import_history --product BTC-USD --timeframe 1h --days 3` against the real Coinbase public endpoint imported **73 candles, 0 rejected, 0 missing intervals**; a second run reported **0 new / 73 duplicates** (live dedup proof). Data sanity: BTC closes ≈ $72.8k–$75.4k over a contiguous 2026-11-08 → 2026-11-11 UTC range, decimal-string precision preserved, source `exchange`. This confirmed the flagged wire-format items 1 and 7 in the checklist (granularity label param, response shape, UNIX-seconds bounds, ordering).

CI from a clean checkout: run [43104165899](https://github.com/jamesdileva/trend-setter/actions/runs/43104165899) — **green** (repo hygiene, engine ruff+mypy+pytest, desktop typecheck+vitest).

## Deviations & follow-ups

- The candles response carries no per-candle product/granularity — the requested context is stamped during parsing (documented in `_parse_candle_page`).
- `end` bounds appear to include the in-progress bucket (73 candles for a 72.8-hour window); the importer windows `[start, end)` and deduplicates, and `requested_buckets` uses ceil so summaries stay honest. Exact edge semantics remain pinned by fixture tests.
- Historical candles are stored `is_complete=True` by definition (wire has no completeness flag); live-feed completeness logic arrives in Sprint 5.
- Rejected candles are counted + reported (missing-range detection covers them) rather than written to a quarantine table — revisit if audit needs grow.
- The operator CLI (`python -m trendbot.tools.import_history`) is the import path until the backtest sprint adds the UI flow (roadmap sequencing).
