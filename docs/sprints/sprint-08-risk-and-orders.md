# Sprint 08 — Risk manager and order lifecycle (mock exchange first)

- **Roadmap sprint:** Sprint 8 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-11

## Goal

Implement the mandatory risk gate and the durable order state machine against the mock exchange: every order intent passes risk, persists before any network call, survives timeouts without blind retries, applies fills idempotently, and reconciles after restarts. Real trading stays disabled.

## Scope

Engine (`engine/`), per architecture.md §9–10 and implementation.md §9:

- `risk/limits.py` + `risk/manager.py` — `RiskLimits` (conservative configurable defaults) and the pure `RiskManager.check()`: stale-data gate, kill switch, cooldown, per-order cap, per-position cap, total exposure cap, open-order/position limits, increment/min-max size validation, cash affordability — each rejection a plain-language reason code
- `risk/sizing.py` — quote→base sizing rounding **down** to increments, min/max validation
- `risk/daily.py` — `DailyLedger`: UTC-day baseline persisted (`daily_accounting`), drawdown vs baseline, survives restart
- `execution/state_machine.py` — legal-transition table for the architecture.md §10 states (`created → risk_approved → submitting → acknowledged → open → partially_filled → filled`, plus rejected / cancel_pending / canceled / unknown_submission / reconciliation_required); illegal transitions raise plain errors
- `execution/intents.py` — `OrderIntentRepository` (durable intents persisted **before** network), deterministic client-order-id identity (same signal bucket → same id), `ExchangeOrderRepository` mapping
- `execution/submit_flow.py` — the safe submission sequence: risk gate → durable intent → `submitting` → adapter → ack/open; timeout with unknown outcome → `unknown_submission` → **never retried blindly** → reconciliation (using the verified duplicate-`client_order_id` protection: re-probing with the same id cannot create a second order); rejection → durable `rejected`
- `execution/fills.py` — idempotent fill application (replayed fills never double-count) updating position snapshots
- `execution/reconcile.py` — `Reconciler`: restart recovery — unresolved intents re-checked against the exchange, unknown outcomes resolved via the duplicate probe, `RECONCILIATION_REQUIRED` states resolved or left safe-paused
- `application/trading_controls.py` — distinct semantics: pause entries / stop trading (cancel entry orders, keep protective management) / emergency stop (kill switch, explicit re-arm) / exit-all (through the same durable, risk-recorded flow)
- Fake exchange: unknown-outcome simulation (order created, response lost), partial/full fill simulation
- Persistence: `OrderIntentRepository`, `ExchangeOrderRepository`, `PositionRepository`, `RiskRepository` (risk events), `DailyLedger` on `daily_accounting`

Out of scope: live Coinbase submission (Sprint 10), protective order types (Sprint 10), trading-schedule windows (later), UI for controls (Sprint 9/11 wires them).

## Acceptance criteria (roadmap Sprint 8 verification)

- [x] Each risk limit has positive and negative tests (stale gate, kill switch, drawdown, cooldown, per-order/position/exposure caps, open-order/position limits, configured + product size bounds, cash)
- [x] Order quantity rounds down correctly (333/100000 → 0.00333 exact; coarse-increment fixture)
- [x] No order reaches the adapter when risk rejects (fake adapter create_calls == 0 after rejections; durable `rejected` intent + risk event)
- [x] Timeout after simulated exchange acceptance does not create a duplicate (unknown-outcome one-shot loss → `unknown_submission` → reconciliation probe with the same id → exactly one exchange order, intent `open`)
- [x] Partial fills update positions correctly (0.001 + 0.003 → 0.004 long, average price tracked)
- [x] Replayed fill events do not double-count (second apply returns False, size unchanged)
- [x] Kill switch blocks new entries; explicit re-arm required (emergency stop persists mode + kill switch; re_arm restores)
- [x] Restart reconstructs unresolved orders and requests reconciliation (intent stuck `unknown_submission` survives in DB; a fresh Reconciler resolves via the duplicate probe)

## Verification

Commands and results (Python 3.14.3):

- `python -m pytest` (in `engine/`) — **334 passed** (+77: risk limits, sizing, state machine table, submission flow, unknown-outcome recovery, fills/positions, reconciliation, daily ledger, trading controls)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 66 source files
- `python scripts/repo_checks.py` — OK: 156 files scanned
- All scenarios run against the mock exchange — the fake gained one-shot unknown-outcome loss (accepted internally, response lost, retry finds the existing order) mirroring the verified duplicate-protection semantics
- CI from a clean checkout: run [43284324587](https://github.com/jamesdileva/trend-setter/actions/runs/43284324587) — **green** (repo hygiene, engine ruff+mypy+pytest, desktop typecheck+vitest)

## Deviations & follow-ups

- Entry checks run in a fixed order (kill switch → stale → drawdown → cooldown → caps → size → affordability); a rejected entry persists the intent in `rejected` with the reason — durable evidence of every attempt.
- Exits bypass entry caps and the stale gate (protective management continues when data is stale, per architecture.md §9); only the kill switch blocks exits, and emergency-stop cancellation is handled by the controller, not the risk gate.
- Cooldown = 3 consecutive failures within a 300 s window (persisted streak); configurable constants in `submit_flow.py`.
- Reconciliation probes resubmit with the **same** client order id — safe by the verified duplicate protection; intents that cannot resolve stay safe-paused and are reported.
- Positions apply fills only (exchange truth wins); a SELL fill on the same exchange order id with a distinct trade id is legitimate and reduces the position — replayed identical fills dedupe.
- Follow-ups: wire the risk manager + submission flow into paper trading (Sprint 9); protective order types and live submission (Sprint 10); risk-limit UI (Sprint 11).
