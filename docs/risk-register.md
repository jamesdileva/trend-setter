# Risk Register

**Purpose:** track the highest-value failure modes for this project. Seeded from the Sprint 0 scope in [`sprint-roadmap.md`](../sprint-roadmap.md). Review every sprint: update status, add new risks, and record closures with evidence (a test or ADR reference).

Severity: Critical / High / Medium / Low. Likelihood: based on current design evidence, re-scored each sprint.

| ID | Risk | Severity | Likelihood | Mitigation / control | Status |
|---|---|---|---|---|---|
| R-01 | Coinbase API credential leakage (repo, logs, diagnostics, DB) | Critical | Medium | Secure OS credential store; secrets never in SQLite/logs; redaction before serialization (architecture.md §6, §12, §19); `scripts/repo_checks.py` secret scan | Open |
| R-02 | Duplicate orders after uncertain submission outcome | Critical | Medium | Durable order intents with unique client order IDs; never blind-retry order creation; reconcile before retry (architecture.md §10). Verified 2026-11-11: reuse of a `client_order_id` does not create a second order — existing order returned per docs (`DUPLICATE_CLIENT_ORDER_ID` failure enum also exists; runtime nuance flagged) — exchange-side idempotency backs up the local design | Open |
| R-03 | Stale or incomplete market data drives decisions | High | Medium | Completeness/freshness gates; no close-of-candle signals on incomplete candles; entry block when data is stale (architecture.md §7). Verified 2026-11-11: WS channels close after 60–90 s without updates — `heartbeats` channel (~1 s counter) must be subscribed for liveness/drop detection | Open |
| R-04 | Local/network outage during live trading | High | Medium | Explicit stop semantics; exchange-side protective orders where verified; UI never implies guaranteed local cancellation (architecture.md §5, §9) | Open |
| R-05 | Database failure, corruption, or migration loss | High | Low | SQLite transactions, FK/journal/busy-timeout setup; backup before migrations; integrity + restore tooling (architecture.md §14) | Open |
| R-06 | Restart/crash/update silently resumes live trading | Critical | Medium | Disarmed-by-default lifecycle; reconciliation required before live resume (architecture.md §5, §13) | Open |
| R-07 | Dependency or supply-chain compromise | Medium | Low | Pinned dependency versions, committed lockfiles, dependency review (implementation.md §3) | Open |

## How to add a risk

Append a row with the next ID, then reflect the mitigation in an architecture/implementation doc or an ADR — a mitigation that lives only in this table is not a mitigation.
