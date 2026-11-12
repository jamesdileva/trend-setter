# Sprint 10 — Live Coinbase execution integration

- **Roadmap sprint:** Sprint 10 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-12

## Goal

Connect the hardened order pipeline to Coinbase with strict safeguards: a real execution adapter (fully offline-tested against documented response shapes), a multi-step live-arming flow with prerequisites and restart disarm, and explicit warnings — **real trading stays disabled until the user deliberately arms it with their own credentials**.

## Scope

Engine (`engine/`), per architecture.md §10, §13 and implementation.md §10:

- `exchange/coinbase_live.py` — `CoinbaseLiveExecutionAdapter`: the full `ExchangeAdapter` interface over the verified REST endpoints (place order with `limit_limit_gtc`/`market_market_ioc` configurations, get order, batch cancel, fills pagination, accounts, products). Coinbase statuses normalized to the internal vocabulary; `client_order_id` passed on every order; network failure during submission raises `UnknownOutcomeError` (no blind retry); 429s back off
- `application/live_trading.py` — `LiveArmingController`: prerequisites (credentials connected, trade permission, reconciliation clean, fresh market data), **two-step arm** (request → confirmation token → confirm), disarm, and a **startup force-disarm** so a restart never silently resumes live trading (R-06)
- `main.py` — forces live-disarmed on every engine startup
- API: `GET /live/status`, `POST /live/arm-request`, `POST /live/arm-confirm {token}`, `POST /live/disarm` — token-gated, plain-language prerequisite failures
- Guard: no withdrawal/transfer endpoint is referenced anywhere in the codebase (AST test)

Documented limitation: the manual live smoke test (tiny size, separately approved) requires the user's own CDP key — every automated test uses mocked HTTP.

Out of scope: protective order automation (stop orders are placeable via the adapter but no automated placement yet), the live engine mode switch in the paper loop (arming gates + adapter land this sprint; the operator wires mode selection with real credentials), trading-schedule windows.

## Acceptance criteria (roadmap Sprint 10 verification)

- [x] Automated tests use mocks only (httpx.MockTransport fixtures — no network, no real keys)
- [x] Permission failure prevents arming (403 → InsufficientPermissionsError; arming prerequisite `trade_permission` must be true)
- [x] Stale data prevents new entries (Sprint 5 gate, re-checked as an arming prerequisite)
- [x] Unknown submission is reconciled before retry (Sprint 8 flow; live adapter raises `UnknownOutcomeError` on network failure after send)
- [x] Exchange balance/order/fill state is authoritative (adapter parses exchange responses into the internal vocabulary)
- [x] A manual, separately approved live smoke test is documented and optional (requires the user's own CDP key — ECDSA, View+Trade, never Transfer)
- [x] No withdrawal/transfer API path exists in the application (source-level guard test on `coinbase_live.py`)
- [x] Restart never silently resumes live trading (`force_disarm()` on every engine startup, tested)
- [x] Two-step arm with a 5-minute token expiry; wrong/expired tokens rejected

## Verification

Commands and results (Python 3.14.3):

- `python -m pytest` (in `engine/`) — **375 passed** (+41: live adapter fixtures — order configurations, status mapping, client-order-id propagation, fills pagination, cancel results, permission failures; arming flow — prerequisites, two-step token, expiry, restart disarm; withdrawal-path guard)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 71 source files
- `python scripts/repo_checks.py` — OK: 168 files scanned
- `GET /live/status`, `POST /live/arm-request`, `POST /live/arm-confirm {token}`, `POST /live/disarm` endpoints wired; `main.py` forces live-disarm on every startup
- CI from a clean checkout: run [43289821806](https://github.com/jamesdileva/trend-setter/actions/runs/43289821806) — **green** (repo hygiene, engine ruff+mypy+pytest, desktop typecheck+vitest)

## Deviations & follow-ups

- The live adapter is complete and tested but **no engine mode routes live orders yet** — the paper engine still uses the fake adapter. Sprint 11 wires mode selection (paper vs armed-live) into the nontechnical UI, gated by the arming controller. This is deliberate: the operator must connect real credentials and arm through the two-step flow before any live order path is reachable.
- The manual live smoke test (tiny size, separately approved by the operator) requires the user's CDP key — ECDSA, View+Trade, never Transfer. Until that key exists and is armed through the two-step flow, no live order can be placed.
- Protective orders (stop-limit) are placeable through the adapter's `limit_limit_gtc` configuration, but automated stop placement is a documented follow-up (Sprint 8's execution layer doesn't yet generate them from strategy decisions).
- Walk-forward evaluation remains a backtest follow-up (Sprint 7 note).
