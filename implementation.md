# Coinbase Automated Trend-Follower — Implementation Guide

**Document:** `implementation.md`  
**Purpose:** Practical engineering conventions and step-by-step implementation guidance  
**Companion documents:** `architecture.md`, `sprint-roadmap.md`

---

## 1. How to use this guide

Implement one sprint at a time from `sprint-roadmap.md`. The roadmap defines scope and acceptance criteria; this guide defines how to organize and build the code.

For each feature:
1. Inspect the current files and tests.
2. Identify the smallest change that completes the feature.
3. State exact file paths being created or changed.
4. Implement the change without removing existing functionality.
5. Run focused tests first, then the full relevant suite.
6. Report what changed, what was tested, and what remains.
7. Do not proceed if a safety-critical test fails.

Avoid large speculative rewrites. Prefer explicit interfaces and small modules.

## 2. Repository layout

Use this structure as the initial target. It may evolve through recorded architecture decisions.

```text
coinbase-trend-follower/
├── apps/
│   └── desktop/
│       ├── electron/
│       │   ├── main.ts
│       │   ├── preload.ts
│       │   └── process-manager.ts
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── hooks/
│       │   ├── services/
│       │   ├── types/
│       │   └── styles/
│       ├── package.json
│       └── vite.config.ts
├── engine/
│   ├── src/trendbot/
│   │   ├── __init__.py
│   │   ├── main.py
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
├── scripts/
├── docs/
├── .gitignore
├── README.md
└── architecture.md
```

### Module ownership

| Module | Owns |
|---|---|
| `api/` | FastAPI routes, schemas, auth and local API boundary |
| `application/` | Use cases, orchestration, lifecycle commands |
| `config/` | Typed settings, validation, config versioning |
| `database/` | Models, migrations, repositories, transaction helpers |
| `exchange/` | Coinbase adapter, normalized exchange types, fake adapter |
| `market_data/` | WebSocket/REST ingestion, candle normalization, aggregation, gap repair |
| `strategies/` | Strategy interface, EMA/RSI baseline, indicator functions |
| `risk/` | Position sizing, exposure, drawdown, kill switch, approval decisions |
| `execution/` | Order intent state machine, submission, cancellation, reconciliation |
| `backtesting/` | Historical simulation and metrics |
| `paper/` | Simulated account and fill model |
| `observability/` | Structured logs, health, diagnostics, redaction |

Do not let `strategies/` import `exchange/` or `execution/`. Strategy output is a decision, not an order.

## 3. Environment and dependency management

- Pin Python dependencies in a lockable project configuration.
- Pin Node dependencies with a committed lockfile.
- Use a supported Python version verified against all selected packages.
- Keep development tools separate from runtime dependencies.
- Do not commit `.env`, private keys, database files, logs, backups, build output, or signing material.
- Use mock exchange fixtures for tests.
- Document reproducible setup commands for developers, but never require them from the end user.

Before committing to a Coinbase SDK, verify current SDK maintenance, authentication compatibility, endpoint coverage, and order-model support. Wrap it behind `CoinbaseAdapter` so SDK changes are localized.

## 4. Core domain types

Prefer explicit typed objects over passing loosely structured dictionaries throughout the engine.

Suggested conceptual types:

```python
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum

class TradingMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"

class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

@dataclass(frozen=True)
class Candle:
    product_id: str
    granularity: str
    start_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_complete: bool

@dataclass(frozen=True)
class StrategyDecision:
    product_id: str
    granularity: str
    candle_time: datetime
    signal: SignalType
    reason_code: str
    explanation: str
    indicator_values: dict[str, str]
    strategy_version: str
    config_hash: str
```

This is illustrative, not a complete implementation. Validate domain invariants at construction or service boundaries. Serialize Decimal values as strings or documented fixed-point units.

## 5. Configuration design

Separate non-secret application settings from secrets.

Example non-secret configuration shape:

```yaml
app:
  timezone_display: local
  log_level: INFO

market:
  products:
    - BTC-USD
    - ETH-USD
  timeframes:
    - 1m
    - 5m
    - 15m
    - 1h
    - 4h

strategy:
  name: ema_rsi_baseline
  fast_ema_period: 20
  slow_ema_period: 50
  rsi_period: 14
  rsi_entry_ceiling: 70

risk:
  max_order_quote_amount: "25.00"
  max_position_exposure: "50.00"
  max_total_exposure: "75.00"
  daily_drawdown_limit_percent: "1.0"

trading:
  default_mode: paper
  live_armed: false
```

Values above are illustrative starter configuration examples, not recommended investment settings. Final defaults must be reviewed and surfaced clearly in the UI. Secrets never belong in this file.

### Configuration rules

- Parse into typed settings models.
- Reject unknown or invalid values where safety requires strictness.
- Validate fast EMA < slow EMA.
- Validate intervals against the supported capability list.
- Store config versions and hashes.
- Apply strategy changes at a completed-candle boundary or after a controlled stop.
- Never change risk limits silently.
- Require confirmation for reducing protections or increasing exposure.

## 6. Coinbase adapter contract

Define an interface before implementing the real adapter. The fake adapter must implement the same contract.

Suggested responsibilities:

```python
class ExchangeAdapter:
    async def test_connection(self): ...
    async def get_accounts(self): ...
    async def get_product(self, product_id): ...
    async def get_historical_candles(self, product_id, granularity, start, end): ...
    async def stream_market_data(self, products, channels): ...
    async def create_order(self, order_request): ...
    async def get_order(self, exchange_order_id): ...
    async def list_open_orders(self): ...
    async def list_fills(self, since=None): ...
    async def cancel_order(self, exchange_order_id): ...
```

Use exact method signatures and data types once current Coinbase API behavior has been verified. Do not make the UI depend on Coinbase response payload shapes.

### Adapter requirements

- Normalize errors into typed internal exceptions.
- Distinguish authentication, permission, validation, rate-limit, network, and exchange-rejection errors.
- Use explicit request timeouts.
- Use bounded exponential backoff with jitter for retryable reads.
- Never automatically retry ambiguous order creation without querying exchange state.
- Redact authorization headers, JWTs, signatures, and private-key material.
- Use exchange metadata for increments and minimum sizes; refresh safely.

## 7. Market data and candle implementation

### Ingestion pipeline

```text
Coinbase REST / WebSocket
          |
          v
Raw message validation
          |
          v
Normalization to internal events
          |
          v
Candle completeness / aggregation
          |
          v
Deduplication and gap detection
          |
          v
SQLite transaction
          |
          v
Strategy input query
```

### Rules

- Normalize timestamps to UTC immediately.
- Keep exchange event time separate from local receipt time.
- Store source granularity and whether aggregation occurred.
- Do not mutate finalized candles without recording a correction event.
- Use a unique candle key.
- Backfill after reconnect before re-enabling strategy entries.
- Track data freshness per product/timeframe.
- Do not use an unfinished candle for a close-of-candle signal.

For aggregation, use UTC-aligned interval boundaries. Open is the first open, high is maximum high, low is minimum low, close is last close, and volume is summed. Validate behavior against fixtures.

## 8. Strategy implementation

Keep indicators pure and independently tested.

Suggested files:
- `strategies/base.py`
- `strategies/decisions.py`
- `strategies/indicators/ema.py`
- `strategies/indicators/rsi.py`
- `strategies/ema_rsi.py`
- `strategies/registry.py`

### Crossover semantics

A bullish cross on completed candle `t` requires:

- `fast[t-1] <= slow[t-1]`
- `fast[t] > slow[t]`

A bearish cross requires:

- `fast[t-1] >= slow[t-1]`
- `fast[t] < slow[t]`

Specify EMA initialization and RSI calculation method (including smoothing convention) and keep it consistent across backtest, paper, and live. Include warm-up history and edge-case fixtures.

### Baseline entry/exit

Initial entry candidate: bullish crossover plus configured RSI filter. Initial exit candidate: bearish crossover or configured protective exit.

Do not assume that an RSI ceiling below 70 is universally beneficial. Make the rule configurable and compare alternatives with out-of-sample testing. Record exact indicator values and reason codes for every signal.

## 9. Risk and order execution

### Separation

```text
Strategy Decision
       |
       v
Order Intent Builder
       |
       v
Risk Manager ---- reject ---> Persist reason / notify
       |
     approve
       |
       v
Durable Order Intent
       |
       v
Execution Adapter
       |
       v
Exchange Order
       |
       v
Order / Fill Reconciliation
       |
       v
Position and PnL updates
```

### Non-negotiable rules

- No direct order submission from strategy code.
- No direct order submission from renderer/UI code.
- Every order passes the risk manager.
- Persist order intent before network submission.
- Use Decimal for amounts, fees, and quantities.
- Round down to exchange increments.
- Treat request timeout as unknown outcome until queried.
- Apply fills idempotently.
- Reconcile after reconnect and before live arming.
- Persist every rejection and risk event.

### State transition testing

Create table-driven tests for all legal transitions and reject illegal transitions. Test partial fills, cancel/fill races, late WebSocket events, duplicated events, and restart during `SUBMITTING`.

## 10. Backtesting and paper execution

Use a shared execution abstraction with separate adapters:
- `HistoricalSimulationAdapter`
- `PaperExecutionAdapter`
- `CoinbaseLiveExecutionAdapter`

Do not use a boolean flag scattered across the codebase to switch between real and simulated order calls. Select an explicit adapter based on a validated mode, and ensure the live adapter is unavailable to paper-mode code paths.

### Backtesting safeguards

- No look-ahead bias.
- Use only data available at decision time.
- Model fees on every fill.
- Model spread and slippage.
- Document intrabar assumptions.
- Use out-of-sample validation.
- Record full config and data-range metadata.

### Paper trading safeguards

- Separate simulated balances from exchange balances.
- Simulated order IDs must not be confused with Coinbase IDs.
- Paper fills must include configured fee/slippage assumptions.
- Persist state across restart.
- Display a persistent PAPER label.

## 11. Local API and desktop process management

### API boundary

- Bind only to `127.0.0.1`.
- Generate a random local token per application session or use an equivalent authenticated IPC channel.
- Keep Electron context isolation enabled and Node integration disabled in renderer.
- Expose only narrow preload methods to the React UI.
- Validate request origin and payloads.
- Keep secrets out of renderer state and local API responses.
- Do not expose a generic “place order” endpoint.

### Process manager

The Electron main process or dedicated supervisor should:
- Resolve the packaged engine executable path.
- Start the engine with controlled arguments.
- Capture stdout/stderr safely.
- Monitor heartbeat and process exit.
- Request graceful shutdown first.
- Escalate only after timeout and record the event.
- Prevent duplicate engine instances.
- Report engine state to UI.
- Follow explicit background-running policy when the window closes.

The engine should not rely on the renderer remaining open. Live mode must remain disarmed after crash/restart unless the user explicitly reviews and arms it again.

## 12. Secure credential storage

Implement a credential-storage abstraction, for example:

```python
class SecretStore:
    def set_secret(self, key: str, value: str) -> None: ...
    def get_secret(self, key: str) -> str | None: ...
    def delete_secret(self, key: str) -> None: ...
```

The Windows implementation should use Credential Manager or DPAPI-backed encryption with correct user scope and file ACLs. Select one approach after a small prototype verifies packaging and recovery behavior.

- Store only a non-secret reference in SQLite.
- Never log secret values.
- Avoid passing private keys through command-line arguments.
- Avoid environment variables if they can be inherited or captured unnecessarily.
- Minimize time secrets remain in process memory.
- Do not include secrets in diagnostics or crash reports.
- Document what happens if the Windows user profile is reset or credentials become unavailable.

The connection wizard must explain the minimum required Coinbase permissions and explicitly prohibit withdrawal/transfer permission.

## 13. Installer and Windows packaging

### Build pipeline

1. Build React renderer.
2. Package Electron main/preload.
3. Build Python engine as a bundled executable or packaged runtime.
4. Assemble app resources and version metadata.
5. Generate installer.
6. Sign artifacts when signing infrastructure is available.
7. Test install/launch/upgrade/uninstall on clean Windows 10 and 11 VMs.

### Packaging concerns

- Resolve paths differently in development and packaged mode.
- Store mutable data outside installation directory.
- Do not assume current working directory.
- Handle spaces and non-ASCII characters in Windows paths.
- Handle antivirus false positives through signing/reproducible builds and clear support instructions.
- Ensure app startup works for standard non-admin users.
- Keep database and secrets when updating.
- Make uninstall data-retention behavior explicit.

### First-run experience

1. Welcome and explanation of paper-first behavior.
2. Coinbase connection optional at first launch; paper/backtest can use imported/public data where supported.
3. Guided connection.
4. Select products and timeframe.
5. Review baseline strategy.
6. Review risk limits.
7. Start with backtest or paper mode.
8. Live trading remains a separate, later, deliberate workflow.

## 14. Logging, diagnostics, and support

Use structured logs with:
- UTC timestamp.
- Level.
- Component.
- Event name.
- Correlation ID.
- Safe context.

Redact secrets before serialization, not merely in the UI. Add rotating file handlers and configurable retention. Keep logs bounded.

Diagnostics export should include:
- Application and engine versions.
- OS version.
- Sanitized settings.
- Connection health and last successful test.
- Database migration and integrity status.
- Recent logs.
- Recent engine events.
- No private key, token, signature, authorization header, or unnecessary account data.

## 15. Testing conventions

### Unit
Pure logic: indicators, candle validation, aggregation, decimal sizing, risk rules, PnL, state transitions.

### Integration
Database repositories, migrations, adapter normalization, WebSocket reconnect, credential storage, fake exchange, backup/restore.

### End-to-end
Desktop-to-engine communication, setup wizard, paper workflow, backtest workflow, stop/restart recovery, installer.

### Required failure tests
- No internet.
- Coinbase unavailable.
- Invalid/expired credentials.
- Permission mismatch.
- Rate limiting.
- WebSocket disconnect.
- Missing candle.
- Stale market data.
- Timeout after order acceptance.
- Partial fill.
- Cancel/fill race.
- Database locked/corrupt/full.
- Process crash during order transition.
- Windows restart.
- Update while engine is active.
- Secret redaction.

No automated test may place a real order. Keep real-money smoke testing separate, manual, and explicitly authorized.

## 16. User-facing wording

Prefer:
- “Paper trading is running. No real orders are being placed.”
- “Live trading is not armed.”
- “Coinbase connection needs attention.”
- “Market data is delayed. New entries are paused.”
- “We could not confirm whether Coinbase received this order. Checking exchange status before trying again.”
- “Your protective order has not been confirmed by Coinbase.”
- “Trading is paused because the daily loss limit was reached.”

Avoid:
- “Guaranteed stop-loss.”
- “Risk-free.”
- “Profitable strategy.”
- “Order succeeded” before confirmed exchange acknowledgment/fill state.
- “Connected” when credentials were accepted but account permissions or data subscription are still unverified.

## 17. Definition of implementation complete

A feature is complete only when:
- Its code is in the correct layer.
- Its input and output contracts are explicit.
- It has unit/integration tests appropriate to its risk.
- Its error and recovery behavior is implemented.
- Its UI state is understandable where applicable.
- Its logs are useful and redacted.
- Its documentation and configuration examples are updated.
- Existing functionality remains intact.
- The sprint's acceptance criteria pass.

The final release must also pass the mandatory Polish + Adversarial Audit sprint in `sprint-roadmap.md`.
