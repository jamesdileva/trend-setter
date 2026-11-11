# Coinbase Automated Trend-Follower — Sprint Roadmap

**Document:** `sprint-roadmap.md`  
**Role:** Primary implementation and verification plan  
**Platform:** Windows 10/11  
**Delivery style:** Small, verifiable increments; paper-first; live trading only after explicit gates

---

## 1. Roadmap rules

This roadmap is the source of truth for implementation sequencing. Complete one sprint at a time. Do not begin a dependent sprint until its exit criteria pass or an explicit decision records why the dependency is being deferred.

### Working rules

- Preserve working functionality when replacing files; inspect the existing implementation before changing it.
- Prefer small feature slices with exact file paths and complete replacement code when requested.
- Do not combine unrelated changes into one debugging step.
- Every sprint includes tests, manual verification, and a documented end state.
- Use a mock Coinbase adapter for automated tests. Never let automated tests place real orders.
- Default to paper mode; live trading remains disabled until the live-readiness gate.
- Keep configuration, database migrations, and secrets backward-compatible where practical.
- Record deviations and unresolved risks rather than silently changing scope.
- Pin dependency versions and keep a reproducible build process.
- No profitability claim is accepted without reproducible, fee-aware, out-of-sample evidence.

## 2. Product-level milestones

| Milestone | Result |
|---|---|
| M0 — Foundation | Architecture, repository, development environment, risk register |
| M1 — Desktop shell | Windows desktop app and bundled engine skeleton |
| M2 — Coinbase connectivity | Guided secure setup and verified market/account connectivity |
| M3 — Data foundation | Historical/live candles persisted and validated |
| M4 — Strategy baseline | Configurable EMA/RSI signals with deterministic tests |
| M5 — Backtesting | Reproducible, fee-aware historical simulations |
| M6 — Paper trading | Live market data with simulated orders and persistent state |
| M7 — Risk and execution | Hardened order state machine and risk controls against a mock exchange |
| M8 — Live trading gate | Explicitly armed live execution with reconciliation and protective controls |
| M9 — User-ready packaging | Installer, upgrade, backup, diagnostics, nontechnical-user UX |
| M10 — Polish + adversarial audit | Reliability, usability, security, performance, and release sign-off |

---

## Sprint 0 — Architecture lock and technical verification

### Goals
- Establish a stable scope and confirm integration assumptions before implementation.
- Verify Coinbase-specific behavior against current official documentation.
- Decide exact package/runtime versions only after compatibility checks.

### Scope
1. Review `architecture.md` and record accepted decisions.
2. Verify current Coinbase Advanced Trade authentication, API-key permissions, REST/WebSocket endpoints, candle granularity, rate limits, product increments, order types, client order ID behavior, and protective-order support.
3. Select supported Python version and pin the dependency matrix.
4. Confirm Electron/React packaging approach and installer toolchain.
5. Define the local data directory and secret-storage design.
6. Define initial risk defaults as conservative configurable values, not as performance claims.
7. Create a threat/risk register covering credential leakage, duplicate orders, stale data, local outage, database failure, and unsafe restart.

### Deliverables
- Architecture decision record (ADR) notes.
- Coinbase integration verification checklist.
- Dependency/version matrix.
- Initial repository and branch conventions.
- Risk register.

### Verification
- Each Coinbase capability has an official documentation reference and a test plan.
- No unsupported API behavior is treated as fact.
- Installer strategy is proven with a minimal hello-world package.
- Data and secret locations are documented.

### Exit criteria
No unresolved assumption blocks the first vertical slice. Any unsupported feature is explicitly removed or assigned a fallback.

---

## Sprint 1 — Repository, development environment, and application skeleton

### Goals
Create a clean monorepo with a desktop shell, Python engine package, local API, database layer, and automated test setup.

### Proposed structure

```text
coinbase-trend-follower/
├── apps/
│   └── desktop/
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── services/
│       │   └── styles/
│       ├── electron/
│       ├── package.json
│       └── vite.config.ts
├── engine/
│   ├── src/trendbot/
│   │   ├── api/
│   │   ├── application/
│   │   ├── config/
│   │   ├── database/
│   │   ├── exchange/
│   │   ├── market_data/
│   │   ├── strategies/
│   │   ├── risk/
│   │   ├── execution/
│   │   ├── backtesting/
│   │   ├── paper/
│   │   └── observability/
│   ├── tests/
│   └── pyproject.toml
├── installer/
├── docs/
├── scripts/
├── .gitignore
├── README.md
└── architecture.md
```

### Tasks
1. Initialize repository and ignore secrets, databases, logs, build output, and virtual environments.
2. Create Python package and test runner.
3. Create Electron + React + TypeScript + Vite shell.
4. Add a minimal FastAPI local service bound to loopback.
5. Add supervisor process skeleton with start/stop/health contracts.
6. Add shared version/build metadata.
7. Add CI checks for lint, type checks, and unit tests.
8. Add a fake exchange adapter interface.

### Verification
- Desktop app opens.
- Engine can start and stop through supervisor.
- UI can read health status from local API.
- API is not reachable from another machine on the LAN.
- Tests pass from a clean checkout.
- No API key or secret is needed.

### Exit criteria
A working desktop shell and independently testable engine skeleton exist.

---

## Sprint 2 — Database foundation, migrations, and durable events

### Goals
Create the local data layer before market or trading behavior depends on it.

### Tasks
1. Define SQLAlchemy models for settings, products, candles, strategy configs, signals, order intents, exchange orders, fills, positions, balances, risk events, engine events, backtests, and daily accounting.
2. Configure SQLite foreign keys, busy timeout, journal mode, and transaction handling.
3. Add Alembic migrations.
4. Add repository interfaces and centralized write ownership.
5. Add UTC timestamp conventions and decimal serialization.
6. Add unique constraints for candles, fills, and event identities.
7. Add database backup, integrity-check, and restore utilities.
8. Add migration backup and failure handling.

### Verification
- Fresh database initializes.
- Migrations upgrade from empty database.
- Duplicate candle/fill insert is rejected or safely deduplicated.
- Financial values round-trip without binary-float corruption.
- Backup restores into a clean database.
- A failed write produces a visible health/error state.

### Exit criteria
All later components can persist and retrieve durable state through tested repositories.

---

## Sprint 3 — Coinbase connection wizard and secure credentials

### Goals
Make connecting Coinbase approachable for a nontechnical user without exposing secrets.

### Tasks
1. Implement a guided connection wizard with plain-language steps.
2. Open the official Coinbase developer/API-key page through the user's browser.
3. Add maintained help text and screenshots only after confirming current Coinbase UI.
4. Collect key identifier and private key through secure controls.
5. Store credentials through Windows Credential Manager or DPAPI-backed storage.
6. Store only a credential reference and status metadata in SQLite.
7. Implement a credential-validation endpoint using a non-trading request.
8. Distinguish invalid credentials, insufficient permissions, network failure, and unsupported account state.
9. Add replace-key, disconnect, and retest flows.
10. Add safe diagnostics that never include secrets.

### Verification
- Invalid key fails with actionable instructions.
- Valid read-only key can pass data/account tests where permissions allow.
- Live-trading permission is separately detected.
- Secret is not found in SQLite, ordinary config files, logs, crash reports, or API responses.
- Disconnect removes the stored credential reference/secret according to documented behavior.
- No test places an order.

### Exit criteria
A nontechnical user can connect, test, replace, and disconnect Coinbase credentials without editing files.

---

## Sprint 4 — Historical market data and candle correctness

### Goals
Build reliable historical data ingestion and storage.

### Tasks
1. Implement Coinbase REST market-data adapter.
2. Verify supported candle granularities and historical request limits.
3. Implement pagination/windowing and rate-limit handling.
4. Import BTC-USD and ETH-USD history.
5. Support 1m, 5m, 15m, 1h, and 4h intervals where supported; aggregate from a verified lower interval where required.
6. Validate OHLCV invariants and timestamps.
7. Deduplicate candles and track missing intervals.
8. Add data freshness and gap detection.
9. Add configurable import date range and progress reporting.

### Verification
- Known fixture data imports with exact expected row counts.
- Repeated import does not duplicate candles.
- Missing intervals are identified.
- Aggregated candles match deterministic test fixtures.
- Invalid candle data is rejected/quarantined.
- Rate-limit responses back off without crashing.

### Exit criteria
The database contains validated historical candles for at least one product/timeframe and supports repeatable imports for all supported combinations.

---

## Sprint 5 — Live market data and reconnect/backfill

### Goals
Maintain a resilient live market feed without using incomplete or stale candles for decisions.

### Tasks
1. Implement WebSocket adapter for supported Coinbase channels.
2. Normalize messages into internal event types.
3. Implement heartbeat and connection health.
4. Reconnect with exponential backoff and jitter.
5. Re-subscribe after reconnect.
6. Detect sequence/time gaps where source semantics allow.
7. Backfill missing candles through REST.
8. Mark candle completeness and freshness.
9. Add stale-data entry gate.
10. Add UI status for connection, last message, and last complete candle.

### Verification
- Disconnect/reconnect fixture recovers.
- Duplicate WebSocket messages do not duplicate stored events.
- Missed candle periods are backfilled.
- Incomplete candles do not trigger close-of-candle strategy signals.
- Stale data blocks new entry intents.
- UI communicates disconnected/degraded states clearly.

### Exit criteria
Live data remains coherent across simulated network failures and recovery.

---

## Sprint 6 — Baseline strategy and configuration

### Goals
Implement the configurable EMA crossover + RSI strategy as a deterministic, independently tested module.

### Baseline configuration
- Fast EMA: 20.
- Slow EMA: 50.
- RSI period: 14.
- RSI entry ceiling: 70.
- Products: BTC-USD and ETH-USD.
- Timeframes: 1m, 5m, 15m, 1h, 4h.

These are starting values only. Do not represent them as optimized or profitable.

### Tasks
1. Define strategy interface and typed decision model.
2. Implement EMA and RSI calculations with documented warm-up behavior.
3. Implement crossover detection using completed candles.
4. Implement exact entry/exit semantics.
5. Prevent duplicate entries while a position or entry order exists.
6. Add configuration validation and safe-boundary application.
7. Version configs and calculate config hash.
8. Persist signal values, candle time, strategy version, config version, and reason.
9. Add UI controls with plain-language descriptions.
10. Add per-product/per-timeframe strategy instance support.

### Verification
- Indicator outputs match known reference fixtures.
- Crossover fires only on actual transition, not every candle above/below.
- Insufficient history returns no signal.
- Repeated evaluation is deterministic.
- Config validation rejects invalid periods.
- Signals are reproducible from stored candles and config.
- No strategy code can call exchange order methods.

### Exit criteria
A user can configure the baseline and inspect reproducible BUY/SELL/HOLD decisions without any order execution.

---

## Sprint 7 — Backtesting engine and evaluation UI

### Goals
Test strategies historically with realistic assumptions and visible limitations.

### Tasks
1. Implement simulated execution adapter.
2. Reuse strategy and risk logic from paper/live paths.
3. Add configurable date range, product, timeframe, and strategy config.
4. Model entry/exit fees, spread, slippage, increments, and partial-fill assumptions.
5. Add equity curve and trade ledger.
6. Calculate net/gross return, drawdown, win rate, profit factor, average win/loss, exposure, trade count, and fees.
7. Add out-of-sample split or walk-forward evaluation.
8. Export results to CSV/JSON.
9. Label assumptions and candle-resolution limitations.
10. Add baseline benchmark.

### Verification
- Hand-calculated small scenarios match expected output.
- Fees reduce net results correctly on both sides.
- No future candle values leak into decisions.
- Same inputs/config produce same results.
- Out-of-sample period is separate from tuning period.
- UI distinguishes historical simulation from paper/live activity.

### Exit criteria
Backtests are repeatable, fee-aware, explainable, and clearly labeled as simulations.

---

## Sprint 8 — Risk manager and order lifecycle (mock exchange first)

### Goals
Implement the mandatory risk gate and durable order state machine before connecting live order submission.

### Tasks
1. Define risk manager interface and decision/rejection reasons.
2. Implement order size and product increment validation using decimal arithmetic.
3. Implement per-order cap, per-position cap, total exposure cap, open-order/position limits, daily drawdown threshold, stale-data gate, and cooldown.
4. Define daily PnL accounting rules and persistence.
5. Implement kill-switch behavior and re-arm workflow.
6. Implement durable order intent and order state machine.
7. Implement unique client order identity where supported.
8. Handle timeout/unknown submission without blind retry.
9. Handle partial fills, cancellation races, rejected orders, and idempotent fill processing.
10. Implement exchange reconciliation interface with fake exchange fixtures.
11. Define stop, pause entries, emergency stop, and exit-all semantics separately.

### Verification
- Each risk limit has positive and negative tests.
- Order quantity rounds down correctly.
- No order reaches adapter when risk rejects.
- Timeout after simulated exchange acceptance does not create a duplicate.
- Partial fills update positions correctly.
- Replayed fill events do not double-count.
- Kill switch blocks new entries.
- Restart reconstructs unresolved orders and requests reconciliation.

### Exit criteria
The mock-exchange execution pipeline is safe, durable, and fully tested. Real trading is still disabled.

---

## Sprint 9 — Paper trading

### Goals
Run the real market-data and strategy pipeline with simulated balances/orders only.

### Tasks
1. Create a paper account isolated from Coinbase balances.
2. Implement simulated fills with fee/spread/slippage assumptions.
3. Persist simulated orders, fills, positions, and balances.
4. Reuse risk manager and strategy engine.
5. Add start, pause entries, stop, and emergency stop controls.
6. Ensure paper mode is visually unmistakable.
7. Add session and cumulative performance summaries.
8. Add restart recovery and paper-account reset/export with confirmation.

### Verification
- No Coinbase order endpoint is called in paper mode.
- Paper balances are never shown as exchange balances.
- Fees and simulated fills are applied consistently.
- State survives app restart.
- Pause entries does not silently abandon protective management.
- Paper mode remains selected after restart unless user changes it explicitly.

### Exit criteria
A paper session can run continuously using live data and simulated execution, with durable records and clear UI status.

---

## Sprint 10 — Live Coinbase execution integration

### Goals
Connect the hardened order pipeline to Coinbase with strict safeguards. This sprint is not a profitability milestone.

### Prerequisites
- Sprints 0–9 pass.
- Paper soak test completed.
- Current Coinbase order and permission behavior verified.
- Mock exchange tests cover ambiguous outcomes and recovery.
- Live trading remains disarmed by default.

### Tasks
1. Implement real order adapter methods supported by current Coinbase API.
2. Validate product increments and order constraints from exchange metadata.
3. Implement live permission check.
4. Add live account reconciliation before arming.
5. Implement live arming confirmation with pair/timeframe/exposure summary.
6. Require successful risk configuration review.
7. Implement submit/query/cancel flow through the durable order state machine.
8. Persist exchange IDs and confirmed fills.
9. Implement reconnect reconciliation.
10. Implement protective order placement/verification where supported.
11. Add explicit warnings for unsupported protective behavior and local-stop outage risk.
12. Add manual disarm and emergency stop.
13. Ensure restart/update never silently resumes live trading.

### Verification
- Automated tests use mocks only.
- Permission failure prevents arming.
- Stale data prevents new entries.
- Unknown submission is reconciled before retry.
- Exchange balance/order/fill state is authoritative.
- A manual, separately approved live smoke test is documented and optional.
- No withdrawal/transfer API path exists in the application.

### Exit criteria
Live execution is technically gated, auditable, reconcilable, and disabled until the user deliberately arms it. No claim of strategy profitability is made.

---

## Sprint 11 — Main dashboard and nontechnical-user experience

### Goals
Turn the functional engine into an understandable daily-use application.

### Pages
1. Overview.
2. Trading / active positions.
3. Strategy configuration.
4. Backtesting.
5. History / orders / fills.
6. Coinbase connection.
7. Settings.
8. Help / diagnostics.

### Tasks
1. Build overview cards for mode, engine, connection, balance, positions, PnL, and risk status.
2. Add candlestick chart with EMA overlays and signal markers.
3. Add trade ledger with filters.
4. Add plain-language strategy controls and validation.
5. Add separate paper/live account presentation.
6. Add clear status and error banners.
7. Add confirmation dialogs for high-impact actions.
8. Add help text, tooltips, and setup walkthrough.
9. Add accessible layout, keyboard navigation, and Windows display scaling.
10. Add safe diagnostics export.

### Verification
- Every displayed value has a defined source and freshness timestamp.
- Stale values are visually marked.
- Paper/live data cannot be confused.
- High-risk controls require confirmation.
- User can complete common tasks without editing files or opening terminal.
- UI recovers gracefully when engine is unavailable.

### Exit criteria
A nontechnical tester can understand the system state and complete setup, paper trading, backtesting, and safe shutdown.

---

## Sprint 12 — Windows packaging, installer, and recovery

### Goals
Deliver a conventional double-click Windows installation and dependable application lifecycle.

### Tasks
1. Bundle Python engine/runtime and all dependencies.
2. Package desktop shell.
3. Create Windows 10/11 x64 installer.
4. Create Start Menu and desktop shortcuts.
5. Create application data directories on first launch.
6. Implement supervisor startup, stop, crash detection, and restart policy.
7. Decide and implement background-running behavior clearly.
8. Add clean uninstall with user-data retention choice.
9. Add database backup before updates/migrations.
10. Add version display and release notes.
11. Add update/rollback workflow; never update while live execution is active.
12. Code-sign installer when feasible.
13. Test install/upgrade/uninstall on clean Windows VMs.

### Verification
- Installs on clean Windows 10 and Windows 11 without Python/Node/Git.
- Desktop shortcut launches app.
- App can start/stop engine.
- Closing UI follows clearly explained background policy.
- Reboot does not silently resume live trading.
- User data and credentials survive an ordinary app update.
- Uninstall behavior is clear and does not silently delete history.
- Failed update can be recovered.

### Exit criteria
A nontechnical user can install, launch, update, and uninstall without developer tools.

---

## Sprint 13 — Operational readiness and paper soak test

### Goals
Test the complete packaged application under realistic operating conditions before release.

### Tasks
1. Run a sustained paper-trading session (target duration set before test; recommended initial target 72 hours).
2. Simulate network interruption and recovery.
3. Simulate Coinbase rate limits and temporary API failures.
4. Simulate application crash and Windows restart.
5. Simulate disk-full and database-write failure.
6. Verify order/fill idempotency with replayed events.
7. Verify backup/restore on a clean install.
8. Measure CPU, RAM, disk growth, and log rotation.
9. Review all warnings and errors for understandable wording.
10. Conduct a friend/usability test using the installer and setup wizard.

### Verification
- No unexplained duplicate trades or fills.
- No silent stale-data trading.
- No credential leakage.
- Engine recovers into a safe, disarmed state.
- Logs remain bounded.
- Backup restore reproduces expected records.
- Tester can explain current mode and how to stop entries.

### Exit criteria
No unresolved critical or high-severity reliability issue remains. All known limitations are documented.

---

## Sprint 14 — Polish + adversarial audit (mandatory final sprint)

This sprint is required, not optional. Do not treat a successful demo as release readiness.

### A. Adversarial architecture and code audit

Review the complete application as an unfriendly failure analyst:
- Find paths that bypass risk checks.
- Find duplicate-order or duplicate-fill paths.
- Find unsafe retries after uncertain outcomes.
- Find race conditions between stop, cancel, fill, and reconnect.
- Find incorrect position, balance, fee, or PnL calculations.
- Find time-zone, candle-boundary, and look-ahead errors.
- Find unsafe restart or live auto-resume behavior.
- Find missing database transactions or migration hazards.
- Find local API exposure, weak IPC authentication, or input-validation gaps.
- Find secret leakage through logs, errors, crash reports, or support bundles.
- Find installer/update/uninstall paths that lose or expose user data.
- Find UI states that misrepresent stale, partial, or unconfirmed exchange state.

### B. Trading correctness audit
- Recalculate selected trades independently from source candles/fills.
- Verify decimal precision and exchange increments.
- Verify fees on every fill.
- Verify partial fills and cancellation races.
- Verify daily loss calculations and restart persistence.
- Verify protective-order status is confirmed, not assumed.
- Verify backtest execution assumptions and no future data leakage.
- Confirm no profitability claims exceed evidence.

### C. Reliability and performance polish
- Profile CPU/RAM/disk use during 1m and multi-pair operation.
- Review WebSocket reconnect loops and REST throttling.
- Review SQLite lock behavior and write batching.
- Check log rotation and backup size.
- Improve startup and shutdown feedback.
- Fix UI loading, empty, degraded, and recovery states.
- Improve error messages and help content.
- Remove dead code, unused dependencies, and noisy logs.

### D. Nontechnical-user acceptance
A tester who did not build the application must be able to:
1. Install it.
2. Launch it.
3. Follow Coinbase setup instructions.
4. Verify connection.
5. Run a backtest.
6. Start paper trading.
7. Understand the selected pair/timeframe/strategy.
8. Pause entries and stop safely.
9. Find trade history and diagnostics.
10. Back up data and understand uninstall behavior.

### E. Release checklist
- [ ] All critical/high audit findings fixed or release-blocked with explicit rationale.
- [ ] Regression suite passes.
- [ ] Clean Windows 10 install passes.
- [ ] Clean Windows 11 install passes.
- [ ] No developer runtime required.
- [ ] Paper mode default confirmed.
- [ ] Live mode disarmed by default.
- [ ] Credential storage and redaction audited.
- [ ] Reconciliation and duplicate-order tests pass.
- [ ] Backup/restore passes.
- [ ] Paper soak test passes.
- [ ] Help and known limitations are included.
- [ ] Installer version and release notes are correct.

### Exit criteria
Release candidate is approved only when critical/high defects are resolved, all mandatory checks pass, and known limitations are visible to the user.

---

## 3. Cross-sprint acceptance requirements

These requirements apply throughout the project:

### Safety
- Strategy never submits orders directly.
- Risk manager is mandatory for every order intent.
- Paper mode cannot call live order submission.
- Live mode is visibly labeled and deliberately armed.
- Restart never silently resumes live execution.
- Unknown submission outcomes are reconciled before retry.
- No withdrawal/transfer capability is implemented.

### Data correctness
- All internal timestamps are UTC.
- Financial ledger values use decimal-safe representation.
- Candles are deduplicated and validated.
- Incomplete/stale candles cannot trigger normal close-of-candle entries.
- Exchange fills are the source of truth for actual positions.

### User experience
- No command-line steps for ordinary use.
- No manual `.env` editing.
- No need to install Python or Node.
- Clear distinction among backtest, paper, and live.
- Plain-language error messages and recovery instructions.

### Delivery quality
- Tests are repeatable.
- Migrations are reversible or have a documented recovery path.
- Dependencies are pinned.
- Installer is tested on clean machines.
- Diagnostics redact secrets.
- Audit findings are tracked to closure.

## 4. Suggested implementation cadence

Do not optimize for the fewest sprints. Prioritize proving each layer before connecting the next. The most important risk reduction is to keep real order execution until after data, strategy, backtesting, risk, order-state, and paper-trading behavior are independently verified.

Recommended first vertical slice:
1. Desktop opens.
2. Supervisor starts engine.
3. Engine exposes health.
4. UI shows health.
5. Engine writes one event to SQLite.
6. UI displays that event.

This proves the core process boundary before adding Coinbase complexity.
