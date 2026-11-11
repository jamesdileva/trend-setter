# Sprint 01 — Application skeleton: desktop shell, local API, supervisor, fake adapter

- **Roadmap sprint:** Sprint 1 (remainder) in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** In progress
- **Date:** 2026-11-11

## Goal

Prove the core process boundary with a vertical slice: the desktop shell opens, the supervisor starts/stops the Python engine, the engine exposes a loopback-only health/status API, the UI displays that status — plus the fake exchange adapter interface that later sprints build against.

## Scope

Engine (`engine/`):

- `src/trendbot/api/` — FastAPI app factory: loopback-enforcement middleware (defense in depth), `GET /health` (unauthenticated), `GET /status` (session-token header), no order endpoints
- `src/trendbot/main.py` — entrypoint: binds `127.0.0.1` only (no host override), port via `--port` (default 8788), session token from `TRENDBOT_LOCAL_TOKEN` env (never argv)
- `src/trendbot/application/` — engine lifecycle state enum + runtime snapshot (architecture.md §5)
- `src/trendbot/market_data/candles.py` — frozen `Candle` domain type with OHLCV validation rules
- `src/trendbot/exchange/` — `ExchangeAdapter` ABC + typed DTOs (field names from the verified product schema) + `FakeExchangeAdapter` with deterministic fixtures that mirror verified Coinbase semantics (duplicate `client_order_id` returns the existing order)
- `pyproject.toml` — runtime deps: fastapi, uvicorn; dev deps: httpx, mypy

Tests: API auth/loopback/health, adapter contract + duplicate-id idempotency, version-metadata consistency.

Desktop (`apps/desktop/`):

- Electron main (`electron/main.ts`): single-instance lock, window with `contextIsolation` on / `nodeIntegration` off, IPC for engine control, engine stop on quit
- Supervisor (`electron/process-manager.ts`): spawn venv engine, per-session token in env (never argv), `/health` polling, state machine stopped → starting → running → stopping → stopped/crashed, duplicate-start guard, graceful stop with escalation timeout
- Preload (`electron/preload.ts`): narrow contextBridge API (`getEngineStatus` / `startEngine` / `stopEngine`)
- React + Vite renderer: status card (PAPER badge, engine state, version), Start/Stop controls
- `package.json` + committed lockfile; typecheck (`tsc`) + vitest unit tests (spawn config, token handling)

CI: desktop job (`npm ci`, typecheck, vitest; Electron binary download skipped) and engine job gains mypy type checks.

Out of scope: real Coinbase adapter (Sprint 4+), database layer (Sprint 2), strategy engine (Sprint 6), packaging/installer (Sprint 12), background-running policy (later decision).

## Acceptance criteria (roadmap Sprint 1 verification)

- [x] Desktop app opens
- [x] Engine can start and stop through supervisor
- [x] UI can read health status from local API
- [x] API is not reachable from another machine on the LAN (loopback binding + middleware)
- [ ] Tests pass from a clean checkout (CI)
- [x] No API key or secret is needed

## Verification

Commands and results (Python 3.14.3, Node 24.14.1, Windows 10):

- `python -m pytest` (in `engine/`) — **71 passed** (16 new API/auth/adapter tests + 46 baseline + version consistency)
- `python -m ruff check .` (in `engine/`) — all checks passed
- `python -m mypy` (in `engine/`) — no issues in 14 source files
- `npm run typecheck` (in `apps/desktop/`) — clean (renderer + electron main)
- `npm test` (in `apps/desktop/`) — **4 passed** (spawn config, token-not-in-argv, POSIX/Windows paths, token generation)
- `npm run build` — electron main + vite renderer build cleanly
- `python scripts/repo_checks.py` — OK: 64 files scanned, no secrets, links present

Live smoke test (vertical slice):

- Engine started directly (`python -m trendbot.main --port 8799`): `/health` 200 with `engine_version 0.1.0` + UTC time; `/status` 200 with valid token (paper / ready_paper); 401 on wrong token; `netstat` shows **`127.0.0.1:8799 LISTENING`** — loopback only, not `0.0.0.0`.
- Full app run (`npx electron .`): the desktop window opened, the supervisor spawned the engine (listener on `127.0.0.1:8788`, health 200), and the UI polled status over IPC. Terminating the Electron process tree stopped the engine with the app — the `before-quit` handler left no orphaned listener (verified via netstat after exit).

## Deviations & follow-ups

- The session token currently travels via the `TRENDBOT_LOCAL_TOKEN` environment variable. `implementation.md` §12 prefers avoiding environment variables where they could be captured unnecessarily; the engine child's env is readable by same-user processes only, which is acceptable for this skeleton. Upgrade path (later sprint): pass the token over a restricted-permission handshake file or named pipe instead.
- During the smoke test, an incorrect PID capture in the test harness (Git Bash job PID ≠ Windows PID) briefly left the engine running; it was cleaned up manually. This was harness error, not app behavior — the app's own stop path was then verified working.
- A starlette deprecation notice (httpx → httpx2) is filtered in `pytest` config; watch the transition in a future dependency review.
- Remaining roadmap follow-ups: SQLite layer (Sprint 2), Coinbase connection wizard (Sprint 3, must instruct ECDSA key selection — see the verification checklist), streaming market data (Sprint 5).
