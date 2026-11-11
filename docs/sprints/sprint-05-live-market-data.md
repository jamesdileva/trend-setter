# Sprint 05 — Live market data, reconnect, and backfill

- **Roadmap sprint:** Sprint 5 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-11

## Goal

Maintain a resilient live market feed without using incomplete or stale candles for decisions: WebSocket ingestion of the verified public channels, completeness/dedupe tracking, reconnect with resubscribe, REST backfill of gaps, the stale-data gate, and connection status in the UI.

## Scope

Engine (`engine/`), per architecture.md §7 and implementation.md §7:

- `src/trendbot/market_data/ws_events.py` — wire-message normalization into internal events (candle updates/snapshots, heartbeats, subscription acks, safely-ignored malformed frames)
- `src/trendbot/market_data/ws_transport.py` — transport abstraction (`AsyncWsTransport` protocol) + the real `websockets`-based transport; live feed stays transport-agnostic and fully testable offline
- `src/trendbot/market_data/live_feed.py` — `CandleFeed`: subscribes **immediately on connect** (verified 5-second deadline), subscribes `candles` + `heartbeats` separately (verified one-channel-per-message), monitors silence (heartbeats ~1 s; verified 60–90 s idle timeout makes them mandatory), reconnects with exponential backoff + jitter and **re-subscribes**, tracks per-channel sequence numbers (gap detection), buffers the in-progress candle and persists only **completed** candles (deduplicated via unique constraints + last-stored tracking), emits gap callbacks for backfill, and maintains a `FeedStatus` snapshot
- `src/trendbot/market_data/freshness.py` — `MarketDataGate`: stale-data entry gate over the newest **complete** candle + feed liveness (blocks with plain-language reasons; consumed by execution in Sprint 8)
- `src/trendbot/market_data/backfill.py` — `GapBackfiller`: fills detected gaps through the Sprint 4 importer (public or authenticated), idempotent by dedup
- API: `GET /market-data/status` (token-gated); `create_app` gains optional feed wiring via FastAPI lifespan (feed runs on the public channels — no credentials needed for market data)
- `main.py` wires the live feed for BTC-USD/ETH-USD
- deps: `websockets` (runtime)

Desktop: market-data status line in the app (feed state, last complete candle age) via the existing token-safe engine request path.

Flagged-item note: whether the WS candles channel accepts a granularity parameter remains **unverified** (checklist item 2) — the feed stores the wire granularity and stamps the configured one; higher timeframes aggregate locally; live soak (Sprint 9) settles it.

Out of scope: strategy consumption of the feed (Sprint 6), paper trading (Sprint 9), user/authenticated channels (needed for order updates, Sprint 8/10).

## Acceptance criteria (roadmap Sprint 5 verification)

- [x] Disconnect/reconnect fixture recovers (resubscribes with candles+heartbeats; status shows reconnecting→connected; reconnect count tracked)
- [x] Duplicate WebSocket messages do not duplicate stored events (same-bucket refresh + stale older events + snapshot replay + unique-key storage, all tested)
- [x] Missed candle periods are backfilled (disconnect and sequence-jump gap callbacks with ranges; `GapBackfiller` fills + dedups; idempotent)
- [x] Incomplete candles do not trigger close-of-candle signals (only completed buckets are persisted; in-progress candles stay in memory)
- [x] Stale data blocks new entry intents (`MarketDataGate`: disconnected / silent feed / no data / stale candle / unknown timeframe, plain-language reasons; incomplete candles don't satisfy the gate)
- [x] UI communicates disconnected/degraded states clearly (market-data card: state labels, last candle age, error alert, warn coloring)

## Verification

Commands and results (Python 3.14.3, Node 24.14.1):

- `python -m pytest` (in `engine/`) — **190 passed** (+31: WS normalization fixtures, live-feed scenarios via scripted transports — subscribe-first, rollover, duplicate suppression, reconnect/resubscribe, silence-forced reconnect with gap callbacks, sequence jumps with idempotent events; freshness gate; backfill idempotency)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 42 source files
- `npm run typecheck` / `npm test` (in `apps/desktop/`) — clean; 11 passed
- `python scripts/repo_checks.py` — OK: 115 files scanned
- Every async scenario runs offline through scripted transports — the `websockets` library is only touched by the real transport adapter (lazy import), never by tests

## Deviations & follow-ups

- The feed persists the wire-granularity candles (`FIVE_MINUTE` per current docs) and stamps the configured granularity; whether the WS candles channel accepts a subscribe-time granularity parameter remains checklist item 2 — settled in the Sprint 9 paper soak with the real socket. Higher timeframes aggregate locally via the Sprint 4 aggregator.
- The feed loops forever with bounded backoff (capped 30 s) while running — a deliberate daemon policy for market data; the supervisor's bounded restart policy (Sprint 12) governs process-level failures. The 8 connections/second IP limit is respected by the capped backoff.
- Silence threshold defaults to 15 s (heartbeats arrive ~1/s) — configurable per feed instance.
- Backfill ranges are best-effort estimates (last stored bucket → now); over-covering is harmless because imports dedup.
- User-channel subscription (authenticated) is deferred to the order-update sprint (8/10) — market data needs no JWT.
