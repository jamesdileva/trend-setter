# Coinbase Automated Trend-Follower — Master Architecture

**Document:** `architecture.md`  
**Status:** Architecture baseline  
**Target platform:** Windows 10 / Windows 11  
**Primary assets:** BTC-USD and ETH-USD  
**Execution modes:** Backtesting, paper trading, live trading

---

## 1. Purpose and product principles

The Coinbase Automated Trend-Follower is a locally hosted desktop application for systematic BTC and ETH trading through Coinbase Advanced Trade. It is intended for a nontechnical end user, so installation, first-run setup, everyday operation, and recovery must not require command-line knowledge.

The application uses a hybrid architecture:

- A Windows desktop shell provides the user experience and manages application lifecycle.
- A Python engine owns market-data ingestion, strategy evaluation, risk checks, order lifecycle, reconciliation, and persistence.
- A local database is the durable source of truth for application-owned records.
- A local dashboard/control API exposes narrowly scoped functions to the desktop UI.
- Coinbase remains authoritative for exchange balances, orders, fills, and actual account state.

### Design principles

1. **Safe by default:** first launch is disconnected or paper-only; live trading is an explicit opt-in.
2. **No hidden execution:** the UI clearly shows the active mode, enabled pairs, timeframe, strategy, and engine status.
3. **Exchange state wins:** local position/order state must be reconciled against Coinbase before resuming live execution.
4. **No duplicate orders:** every order intent has a durable unique identity and is reconciled after uncertain API outcomes.
5. **Explainable decisions:** signals, risk rejections, orders, fills, and exits are recorded with reasons.
6. **Local-first:** no mandatory cloud service, account, subscription, or hosted backend.
7. **Least privilege:** API credentials are restricted to the required Coinbase capabilities; withdrawal/transfer permissions are never requested.
8. **Operational simplicity:** install, configure, start, pause, stop, update, backup, and restore through the application wherever practical.
9. **Measured performance:** 1-minute and 5-minute strategies are supported but must pass fee-, spread-, slippage-, and latency-aware validation.
10. **No profitability promises:** backtest results are estimates, not guarantees of future performance.

## 2. Scope

### Initial release

- Windows 10/11 installer and desktop application.
- Coinbase Advanced Trade connection wizard.
- Secure local credential storage.
- BTC-USD and ETH-USD market data.
- 1m, 5m, 15m, 1h, and 4h candle intervals, subject to Coinbase endpoint/channel support and aggregation rules.
- Historical candle retrieval and local storage.
- Configurable EMA crossover + RSI baseline strategy.
- Backtesting with fees, spread/slippage assumptions, and out-of-sample evaluation.
- Paper trading against live market data.
- Live trading behind explicit safeguards.
- Configurable pair, timeframe, indicators, position sizing, stop rules, daily loss limit, and trading schedule.
- Trade/order ledger, signals, portfolio view, charts, engine health, and diagnostic logs.
- Local backup/export and restore workflow.
- Graceful shutdown and restart recovery.

### Explicitly out of initial scope

- High-frequency or latency-arbitrage trading.
- Guaranteed-profit or AI-predictive trading claims.
- Custody of funds or handling withdrawals/transfers.
- Publicly hosted dashboard or remote control over the internet.
- Multi-user accounts, cloud synchronization, or broker abstraction beyond Coinbase.
- Unattended automatic software updates that can silently change trading behavior.
- Multiple complex strategies before the baseline is testable and stable.

## 3. System context and component architecture

```text
+--------------------------------------------------------------+
|                 Windows Desktop Application                  |
|                                                              |
|  Setup Wizard | Dashboard | Strategy Settings | Controls     |
+-------------------------------+------------------------------+
                                |
                     Local authenticated IPC/API
                                |
+-------------------------------v------------------------------+
|                    Application Supervisor                    |
|  Engine lifecycle | Health checks | Safe stop | Recovery      |
+-------------------------------+------------------------------+
                                |
+-------------------------------v------------------------------+
|                       Python Trading Engine                   |
|                                                              |
|  Market Data -> Candle Builder/Validator -> Strategy Engine   |
|       |                    |                    |              |
|       v                    v                    v              |
|  Coinbase WS/REST     Historical Store     Signal Evaluator   |
|                                                |              |
|                                                v              |
|  Risk Manager <-------------------------- Order Intent        |
|       |                                                        |
|       v                                                        |
|  Execution Adapter -> Coinbase REST -> Order/Fill Reconcile   |
+-------------------------------+------------------------------+
                                |
+-------------------------------v------------------------------+
|                        Local SQLite                           |
| Candles | Signals | Orders | Fills | Positions | Events       |
| Config Versions | Risk Events | Backtests | Health            |
+--------------------------------------------------------------+
                                |
                     Read-oriented query API
                                |
+-------------------------------v------------------------------+
|                    Desktop Dashboard/UI                       |
| Charts | Portfolio | Trade History | Health | Configuration  |
+--------------------------------------------------------------+
```

### Components and ownership

| Component | Responsibility | Must not do |
|---|---|---|
| Desktop shell | Setup, navigation, process lifecycle, user feedback | Calculate or execute trading decisions |
| Supervisor | Start/stop engine, health monitoring, safe shutdown | Bypass risk checks |
| Engine | Coordinate data, strategy, risk, execution | Depend on UI being open |
| Market data adapter | Coinbase WebSocket/REST ingestion and normalization | Treat incomplete candles as final |
| Candle service | Validate, deduplicate, persist, and expose candles | Silently fabricate missing candles |
| Strategy engine | Deterministic indicator and signal calculation | Place orders |
| Risk manager | Approve/reject order intents and enforce limits | Be bypassed by strategy or UI |
| Execution adapter | Submit/cancel/query orders and reconcile results | Assume request success means fill |
| Database repository | Durable local persistence | Store plaintext API private keys |
| Local API | Expose scoped commands and read models | Listen on public network interfaces |
| Dashboard | Display state and submit allowed control requests | Hold exchange credentials or call Coinbase trading endpoints directly |

## 4. Recommended technology stack

The stack should remain intentionally small and maintainable.

| Area | Recommendation | Notes |
|---|---|---|
| Desktop shell | Electron + React + TypeScript | Familiar desktop packaging and polished Windows UX |
| UI build | Vite | Fast local development and static UI build |
| Engine | Python 3.11+ (pin an actively supported version) | Quant/data ecosystem; exact version selected after dependency compatibility tests |
| Local service | FastAPI bound to loopback only | Typed local API between UI/supervisor and engine |
| Process control | Dedicated supervisor/engine process | UI closure must not accidentally leave an unmanaged engine |
| Database | SQLite with SQLAlchemy + Alembic | Migrations, transaction handling, local persistence |
| Data processing | pandas + NumPy | Indicator and backtest calculations |
| Indicators | Implement core EMA/RSI internally or use a pinned, tested library | Avoid dependency on an unstable indicator package; verify formulas against reference fixtures |
| Exchange | Coinbase Advanced Trade API adapter | Encapsulate official REST/WebSocket interfaces; pin SDK or use a narrow direct adapter |
| Charts | Lightweight Charts or an actively maintained React chart library | Candlestick charts and overlays |
| Logging | Python `logging` with rotating structured log files | Redact credentials and sensitive request headers |
| Windows secrets | Windows Credential Manager or DPAPI-backed encryption | Never plain `.env` in the installed user workflow |
| Packaging | PyInstaller for Python components; Electron Builder for desktop; Inno Setup or equivalent installer | Build and sign artifacts where feasible |
| Tests | pytest, React Testing Library, Playwright, integration tests | Include deterministic fixtures and fake exchange |
| Installer validation | Clean Windows 10/11 virtual machines | Test without Python, Node, Git, or developer tools installed |

**Technology decision note:** The Coinbase SDK, API version, authentication flow, supported WebSocket channels, candle intervals, order types, and rate limits must be verified against current official Coinbase documentation during the integration sprint. Keep Coinbase-specific details behind adapters so a changed SDK does not spread through the application.

## 5. Application process and lifecycle

### Process model

- The desktop shell is the primary user-facing application.
- A supervisor starts and monitors the Python engine.
- The engine can continue operating when the dashboard window is closed only if the user explicitly chooses a background-running mode and the supervisor remains active.
- The UI communicates with a loopback-only local API using a per-installation/session token or equivalent local authentication.
- API endpoints that alter configuration or engine state are separated from read-only endpoints.
- The local API must reject non-loopback connections and apply request validation.

### Lifecycle states

`NOT_CONFIGURED -> READY_PAPER -> RUNNING_PAPER -> STOPPING -> READY_PAPER`

Live lifecycle:

`LIVE_NOT_ARMED -> LIVE_ARMING -> LIVE_READY -> RUNNING_LIVE -> STOPPING -> RECONCILING -> LIVE_NOT_ARMED`

Error states include `DEGRADED`, `SAFE_HALT`, and `RECOVERY_REQUIRED`.

The application must not automatically resume live trading after a crash, OS restart, update, or uncertain exchange state without reconciliation and a clear user policy. Default behavior is to restart in a non-trading state and require the user to review status.

### Stop semantics

- **Pause entries:** stop opening new positions but continue managing existing positions according to the configured exit policy.
- **Stop trading:** stop new entries, cancel eligible open entry orders, reconcile open orders/positions, and continue protective management if the user-selected policy requires it.
- **Emergency stop:** block new orders immediately, attempt configured cancellation actions, and report that exchange-side protective orders may remain active. Never imply that a local button can guarantee cancellation or liquidation during a network outage.
- **Exit all positions:** separate, explicitly confirmed action; not equivalent to stopping the engine.

## 6. Coinbase integration architecture

Create a `CoinbaseAdapter` interface and keep the rest of the application exchange-agnostic.

### Required adapter capabilities

- Validate credentials and account access.
- Retrieve supported products and product increments.
- Retrieve account balances and relevant account metadata.
- Subscribe to supported market-data WebSocket channels.
- Retrieve historical candles.
- Submit supported order types.
- Query order status and fills.
- Cancel orders where supported.
- Reconcile open orders, fills, and balances.
- Normalize Coinbase errors, rate-limit responses, timestamps, and decimal values.

### Guided connection wizard

1. Explain why API access is needed and what the application can and cannot do.
2. Open the official Coinbase developer/API-key page using the user's browser.
3. Show current, maintained instructions for creating an Advanced Trade API key.
4. Tell the user to grant only required view and trade capabilities.
5. Explicitly warn not to grant transfer/withdrawal permissions.
6. Collect the API key identifier/name and private key in secure input controls.
7. Store the secret immediately in Windows Credential Manager or DPAPI-protected storage; do not persist it in ordinary app settings.
8. Validate credentials with a non-trading request.
9. Verify required account/product permissions and show a clear pass/fail result.
10. Provide a safe disconnect, replace-key, and credential-test workflow.

Do not embed API credentials in the installer, database, logs, crash reports, UI telemetry, or source code. The private key must never be returned by the local API after storage.

### Permission model

- Read-only access is sufficient for data-only and paper-only usage where Coinbase supports the required access.
- Live trading requires the minimum trade permission needed for supported order actions.
- No withdrawal/transfer permission.
- The app must clearly distinguish credential validity from permission sufficiency.
- A failed credential test must not trigger a live order.

### Exchange truth and reconciliation

Coinbase is authoritative for actual balances, orders, and fills. The local database records intent and history, but cannot override exchange truth.

On startup and after reconnect:
1. Fetch balances and open orders.
2. Fetch recent order/fill history with overlap to avoid missing events.
3. Match exchange order IDs to local intents.
4. Resolve unknown submission outcomes before retrying.
5. Detect manual trades or orders placed outside the app.
6. Recompute actual positions from confirmed fills.
7. Enter `RECOVERY_REQUIRED` if state cannot be reconciled safely.

## 7. Market-data architecture

### Supported initial markets and timeframes

- Products: `BTC-USD`, `ETH-USD`.
- Timeframes: 1m, 5m, 15m, 1h, 4h.
- Timeframes are configurable per strategy instance, subject to exchange support and data availability.

The implementation must verify Coinbase's current supported candle granularities and WebSocket candle semantics. If a requested timeframe is not directly supported by the source, aggregate from a sufficiently granular base interval using UTC-aligned boundaries and validated OHLCV rules.

### Candle model

Each candle includes:
- Product ID.
- Granularity.
- Start timestamp in UTC.
- Open, high, low, close.
- Volume.
- Source and completeness status.
- Ingestion timestamp.

Use decimal-safe storage for prices/quantities where appropriate. Do not use binary floating-point for order quantities, quote amounts, or financial ledger totals. Indicator calculations may use floating-point arrays after validated conversion.

### Candle correctness

- Never evaluate a strategy on an incomplete candle unless the strategy explicitly supports intrabar evaluation.
- Deduplicate on `(product_id, granularity, start_time)`.
- Validate `high >= max(open, close)`, `low <= min(open, close)`, and nonnegative volume.
- Track gaps and fetch missing historical candles.
- Use UTC internally; convert to local time only for display.
- Record whether a candle is exchange-provided or locally aggregated.
- Avoid look-ahead bias: a signal using a candle may only execute after that candle is complete and the decision can realistically be made.

### WebSocket resilience

- Heartbeat/health monitoring.
- Reconnect with exponential backoff and jitter.
- Re-subscribe after reconnect.
- Backfill candles after gaps.
- Avoid duplicate event processing.
- Mark data stale when freshness thresholds are exceeded.
- Block new entries when required market data is stale or incomplete.

## 8. Strategy architecture

### Strategy interface

Strategies are deterministic components that consume validated market history and produce a signal or no signal. They cannot call the exchange or submit orders.

Conceptual contract:

```python
class Strategy:
    def validate_config(self, config): ...
    def required_history(self, config) -> int: ...
    def evaluate(self, candles, position, config) -> StrategyDecision: ...
```

A `StrategyDecision` should include:
- `BUY`, `SELL`, or `HOLD` (or a typed entry/exit intent).
- Product and timeframe.
- Decision candle timestamp.
- Indicator values used.
- Reason code and human-readable explanation.
- Strategy name/version and configuration hash.

### Baseline strategy: EMA crossover + RSI filter

Initial configurable parameters:
- Fast EMA period: 20.
- Slow EMA period: 50.
- RSI period: 14.
- RSI entry ceiling: 70 (baseline example; validate/tune).
- Optional RSI exit/floor rule, disabled until explicitly specified.
- Optional trend confirmation and cooldown settings, later extension points.

Baseline logic:
- Entry candidate: fast EMA crosses above slow EMA on a completed candle and RSI passes the configured filter.
- Exit candidate: fast EMA crosses below slow EMA, or a configured protective exit condition triggers.
- HOLD: no valid entry/exit condition.

Important: The overview's phrase “RSI below 70” is not sufficient by itself to prove momentum quality. Treat it as a configurable filter, document its exact semantics, and compare alternatives during backtesting. Avoid repeated BUY signals while already in a position.

### Multi-timeframe behavior

Each strategy instance has one explicit decision timeframe. The initial release should not silently mix indicators from different intervals. Later, a strategy may declare a higher-timeframe confirmation input, with all timestamps aligned and no future data leakage.

### Configuration validation

- Fast EMA must be less than slow EMA.
- Indicator periods must be positive and within validated bounds.
- Enough historical candles must exist before signals are enabled.
- Unsupported intervals and product combinations are rejected with a plain-language message.
- Configuration changes are versioned and take effect at a safe candle boundary unless a change requires stopping the engine.
- Record the active config version/hash with every signal and order intent.

## 9. Risk management architecture

Risk checks are a mandatory gate between strategy decisions and order submission. No strategy or UI component can bypass them.

### Required controls

- Maximum quote amount per order.
- Maximum percentage of account equity allocated per position.
- Maximum total exposure across configured products.
- Maximum daily realized and unrealized drawdown threshold.
- Maximum number of open positions and pending entry orders.
- Minimum expected reward after estimated fees/spread/slippage.
- Product minimum/maximum size and increment validation.
- Stale-data and connectivity gates.
- Cooldown after loss or repeated order failures.
- Manual live-trading arm/disarm.
- Optional trading schedule and daily entry limit.

The initial example values in the source overview (2–5% risk and 3% daily drawdown) are not validated recommendations. Defaults must be conservative, transparent, configurable, and reviewed before live use. The app should not imply that a percentage-risk setting guarantees a maximum loss; gaps, slippage, fees, partial fills, and outages can exceed estimates.

### Position sizing

Use a documented sizing method based on available quote balance, configured exposure cap, instrument constraints, and risk budget. Calculate with decimal arithmetic and round down to exchange increments. Reject orders that fall below minimum size or exceed any cap.

### Protective exits

- Prefer exchange-supported protective orders where suitable and verified.
- Track whether protective orders are accepted, open, partially filled, canceled, or rejected.
- Do not report a stop as active until Coinbase confirms it.
- Define fallback behavior when exchange-side protection is unavailable.
- Explain that a local stop cannot execute during a local/network outage.
- Do not assume a trailing stop can be implemented as an exchange-native order for every product/order type; validate current support.

### Daily loss accounting

Define the daily boundary (UTC initially, configurable only with careful accounting), included fees, realized PnL, unrealized PnL, deposits/withdrawals/manual trades, and treatment of open positions. Persist the daily baseline and avoid resetting it on app restart. If account activity outside the bot makes attribution uncertain, flag it.

### Kill switch

When a configured threshold or critical invariant is breached:
1. Persist the triggering event.
2. Block new entry intents.
3. Apply configured cancellation behavior to pending entry orders.
4. Continue protective exit management only when safe and specified.
5. Notify the user in the UI.
6. Require review/re-arm before resuming live entries.

## 10. Execution and order lifecycle

Model orders as durable state machines, not one-shot HTTP calls.

Suggested states:

`CREATED -> RISK_APPROVED -> SUBMITTING -> ACKNOWLEDGED -> OPEN -> PARTIALLY_FILLED -> FILLED`

Other states: `REJECTED`, `CANCEL_PENDING`, `CANCELED`, `EXPIRED`, `UNKNOWN_SUBMISSION`, `RECONCILIATION_REQUIRED`.

### Safe submission sequence

1. Create and commit a unique local order intent.
2. Run risk and product-increment validation.
3. Generate a deterministic client order ID/idempotency identity where supported.
4. Submit to Coinbase.
5. Persist exchange response and exchange order ID.
6. If timeout/connection loss occurs, mark outcome unknown and query Coinbase before retrying.
7. Process order updates and fills idempotently.
8. Reconcile balances and position quantities.

Never blindly retry a create-order request after a timeout. The request may have succeeded even if the response was lost.

### Fees and profitability

- Record actual fees from fills whenever available.
- Backtests must model fees on both entry and exit.
- Include spread and slippage assumptions.
- Show gross PnL and net PnL separately.
- Avoid assuming a maker fee when the order may execute as taker.
- Fee tiers and rates are account-dependent and may change; do not hardcode the overview's example rates as facts.

## 11. Backtesting architecture

Backtesting must use the same strategy and risk logic as paper/live modes wherever possible, with a simulated execution adapter.

Required capabilities:
- Historical candle import and caching.
- Configurable product/timeframe/date range.
- Fee, spread, and slippage assumptions.
- Position sizing and risk limits.
- Stop/exit simulation with explicit candle-resolution limitations.
- Out-of-sample or walk-forward evaluation.
- Baseline benchmark comparison.
- Results export.

Metrics:
- Net return and gross return.
- Maximum drawdown.
- Number of trades.
- Win rate.
- Average win/loss.
- Profit factor.
- Exposure/time in market.
- Fees and estimated slippage.
- Equity curve.
- Per-product and per-period breakdown.

Avoid overfitting by recording all tested parameter sets and separating development data from validation data. Candle-only backtests cannot reliably model intrabar order sequencing; document assumptions and use finer-grained data or conservative execution assumptions where needed.

## 12. Paper trading architecture

Paper trading uses live market data but never submits real orders.

- Simulated account balance is separate from Coinbase account balance.
- Simulated fills use configurable realistic assumptions.
- Fees and spread/slippage are modeled.
- Open positions and orders persist across restarts.
- The UI permanently labels the mode as PAPER.
- Paper orders cannot be converted into live orders.
- Paper and live histories are clearly separated.

## 13. Live trading safeguards

Live trading requires all of the following:
- Valid Coinbase credentials.
- Verified required permissions.
- User-selected live mode.
- Explicit risk configuration review.
- Clear account/product summary.
- Confirmation of the exact pair(s), timeframe(s), and maximum order/exposure limits.
- A deliberate arm action, with a visible live indicator.
- Successful exchange reconciliation.
- Fresh market data and healthy engine state.

Do not use a single easily misclicked toggle as the only live-trading safeguard. Provide a confirmation step and a clear disarm action. On restart after crash/update/reboot, default to disarmed until reconciliation and user review.

## 14. Database design

Use SQLite with migrations. Enable foreign keys, appropriate journal mode, busy timeout, and transactional writes. Keep write ownership centralized in the engine/repository layer; the dashboard should query through the local API rather than opening the DB for arbitrary writes.

### Core tables

| Table | Purpose |
|---|---|
| `app_settings` | Non-secret application settings |
| `credential_metadata` | Credential reference/status only; never private key material |
| `products` | Supported product metadata and increments |
| `candles` | Validated OHLCV candles with unique product/interval/time key |
| `strategy_configs` | Versioned strategy settings and config hash |
| `signals` | Signal decisions and indicator evidence |
| `order_intents` | Durable local order requests and risk decision |
| `exchange_orders` | Exchange order IDs, statuses, and timestamps |
| `fills` | Individual confirmed executions and fees |
| `positions` | Derived/current position snapshots |
| `balance_snapshots` | Timestamped exchange and paper balances |
| `risk_events` | Limits, rejections, kill-switch events |
| `engine_events` | Lifecycle, connectivity, and recovery events |
| `backtest_runs` | Backtest configuration and summary |
| `backtest_trades` | Simulated trade-level results |
| `daily_accounting` | Daily baseline, PnL, and drawdown state |
| `schema_migrations` | Migration history (managed by migration tool) |

### Persistence rules

- Store monetary values and quantities as decimal strings or fixed-precision integer units with documented scale.
- Store timestamps in UTC.
- Use unique constraints to prevent duplicate candles, fills, and event processing.
- Preserve immutable order/fill history; corrections are additive audit events.
- Use transactions for state transitions.
- Back up database before migrations and updates.
- Do not hold a write transaction while waiting for network I/O.
- Provide integrity check and restore tooling.

## 15. Local API and UI boundary

The local API is not a public service. Bind to `127.0.0.1` only, use a random local session token, validate origin/requests, and reject remote interfaces.

Example endpoint groups:

**Read models**
- `GET /health`
- `GET /status`
- `GET /account/summary`
- `GET /balances`
- `GET /positions`
- `GET /orders`
- `GET /fills`
- `GET /signals`
- `GET /candles`
- `GET /performance`
- `GET /logs/recent`
- `GET /configuration`

**Commands**
- `POST /engine/start-paper`
- `POST /engine/request-stop`
- `POST /engine/pause-entries`
- `POST /engine/resume-entries`
- `POST /engine/emergency-stop`
- `POST /configuration/validate`
- `POST /configuration/apply`
- `POST /coinbase/test-connection`
- `POST /live/arm`
- `POST /live/disarm`
- `POST /backup`

Live order submission is not exposed as a generic UI endpoint. Only the engine execution path can submit orders after risk approval.

## 16. Desktop UX and nontechnical-user requirements

### Primary navigation

- Overview
- Trading
- Strategy
- Backtesting
- History
- Coinbase Connection
- Settings
- Help / Diagnostics

### Overview screen

Must clearly show:
- PAPER or LIVE mode (highly visible).
- Engine status and last update.
- Coinbase connection status.
- Selected pairs and timeframes.
- Current balances and positions, with paper/live distinction.
- Daily PnL and configured loss limit.
- Active protective orders/status where available.
- Recent signals, trades, and errors.
- Start, pause entries, stop, and emergency stop controls with distinct semantics.

### Usability requirements

- Plain-language explanations; avoid unexplained trading jargon.
- Use confirmation dialogs for destructive/high-risk actions.
- Display units and currencies consistently.
- Show empty states and actionable error messages.
- Never present stale data as current.
- Include contextual help for API setup and strategy settings.
- Provide a diagnostics export that redacts credentials.
- Support Windows display scaling and keyboard navigation.
- Avoid requiring the user to edit JSON, environment variables, or source files.

## 17. Installer, updates, and file locations

### Packaging

- Build a Windows desktop installer for Windows 10/11 x64 initially.
- Bundle the desktop UI, Python runtime, engine, and dependencies.
- Install shortcuts and register normal uninstall behavior.
- Avoid requiring administrator rights unless a specific installer capability truly needs them.
- Test on clean Windows machines with no developer tools installed.
- Code-sign installer and executables when practical; clearly document unsigned-build warnings during development.

### Data locations

Separate immutable program files from mutable user data. Use Windows known folders / application-data conventions, for example:
- Program files: installation directory.
- Database/config/logs/backups: `%LOCALAPPDATA%` or `%APPDATA%` application-specific directory, selected deliberately.
- Secrets: Windows Credential Manager or DPAPI-backed storage.

Uninstall should explain whether user data is retained. Default uninstall should not silently delete trading history or backups.

### Updates

- Updates must not overwrite user data or secrets.
- Back up database before schema migrations.
- Do not auto-update while live trading is active.
- Require engine shutdown and safe reconciliation before update.
- Provide rollback/recovery for failed updates.
- Clearly show version and release notes.

## 18. Security, privacy, and reliability

- No remote dashboard by default.
- No public listening ports.
- No secrets in logs, crash dumps, screenshots, support bundles, or analytics.
- Restrict file permissions on data and backup directories.
- Validate all IPC/API input.
- Pin dependencies and scan build dependencies.
- Avoid executing downloaded code or strategy plugins in the initial release.
- Redact account identifiers where practical in diagnostic exports.
- Keep an audit trail of user actions that affect live mode or risk configuration.
- Handle system clock drift and timestamp anomalies.
- Use bounded retries and backoff; avoid retry storms.
- Detect disk-full and database-write failures and enter a safe state.
- Use graceful shutdown and durable state transitions.
- Provide clear backup/restore and diagnostic workflows.

## 19. Observability and supportability

Structured logs should include timestamp, severity, component, event type, correlation ID, and safe context. Never include private keys, JWTs, signatures, authorization headers, or full credential payloads.

Expose:
- Engine heartbeat and uptime.
- WebSocket connection state and last message time.
- Last complete candle per product/timeframe.
- REST request health and rate-limit/backoff status.
- Last successful account reconciliation.
- Database health and free disk space.
- Active strategy/config version.
- Last order transition and unresolved order count.

A one-click diagnostics bundle should include version, sanitized configuration, recent logs, health snapshot, and migration status, excluding secrets and unnecessary personal data.

## 20. Testing strategy

### Unit tests
- Indicator calculations and crossover edge cases.
- Candle aggregation and validation.
- Decimal rounding and product increments.
- Position sizing and exposure caps.
- Daily PnL/drawdown accounting.
- Risk rejection rules.
- Order state transitions and idempotent fill processing.

### Integration tests
- Coinbase adapter against mocked HTTP/WebSocket fixtures.
- Authentication failure and permission mismatch.
- Rate limits, disconnects, reconnects, and stale data.
- Timeout after successful order submission.
- Partial fill, cancel race, rejected order, and unknown order status.
- Database migrations, backup, restore, and concurrent reads.

### End-to-end tests
- First-run setup without API credentials.
- Paper-mode connection and operation.
- Backtest workflow and results.
- Live arming safeguards using a fake exchange.
- Graceful stop and restart recovery.
- Installer, upgrade, rollback, and uninstall on clean Windows 10/11 environments.

No automated test should place a real-money order. Live exchange smoke tests must be explicitly manual, separately authorized, and use the smallest permitted test action only if appropriate.

## 21. Key architectural decisions and open verification items

| Decision | Baseline |
|---|---|
| Local-first | Yes |
| Desktop shell | Electron + React |
| Engine | Python, separate process |
| Local API | FastAPI on loopback |
| Database | SQLite |
| Initial assets | BTC-USD, ETH-USD |
| Timeframes | 1m, 5m, 15m, 1h, 4h |
| Baseline strategy | Configurable EMA crossover + RSI |
| Modes | Backtest, paper, live |
| Default mode | Paper / non-live |
| Secret storage | Windows Credential Manager or DPAPI |
| Installer | Bundled Windows installer |
| Remote access | Out of scope |
| Live auto-resume | Disabled by default |

Before implementation, verify from current official Coinbase documentation:
- Current CDP API key creation and authentication requirements.
- Required key permissions for account reads, market data, and trading.
- Current REST and WebSocket endpoints/channels.
- Supported candle granularities and historical candle limits.
- Product increments, minimum sizes, and order types.
- Client order ID semantics and duplicate handling.
- Rate limits and retry guidance.
- Availability/behavior of protective and trailing order types.

These are integration verification tasks, not assumptions to hardcode into the architecture.

## 22. Definition of done for the product

The initial product is ready for a controlled release when:
- A nontechnical user can install and launch it on clean Windows 10/11.
- Coinbase setup is guided and credentials are stored securely.
- Backtesting and paper trading work without trade permissions.
- Live mode cannot be armed without all safeguards passing.
- Exchange orders/fills reconcile correctly after disconnects and restarts.
- No duplicate order is created by an uncertain retry.
- Risk limits and kill-switch behavior are tested.
- The UI clearly distinguishes paper and live state.
- Backups and diagnostics work without exposing secrets.
- A paper-trading soak test and final adversarial audit have passed.
