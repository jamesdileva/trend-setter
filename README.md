# trend-setter

**Coinbase Automated Trend-Follower** — a local-first Windows desktop application for systematic BTC-USD and ETH-USD trading on Coinbase Advanced Trade: an Electron + React desktop shell driving a Python trading engine, with backtesting, paper trading by default, and live trading behind explicit, deliberate safeguards.

> **Status: early development (roadmap sprints 0–1).** Nothing here places real orders. There are no profitability claims — backtests are estimates, not guarantees. See [architecture.md](architecture.md) §1 for the product principles.

## Documentation suite

| Document | Purpose |
|---|---|
| [architecture.md](architecture.md) | Master architecture: components, strategy, risk, execution, data, security, testing |
| [implementation.md](implementation.md) | Engineering guide: repo layout, conventions, adapter contracts, testing |
| [sprint-roadmap.md](sprint-roadmap.md) | Sprint-by-sprint plan with acceptance criteria (source of truth for sequencing) |
| [vps-deployment.md](vps-deployment.md) | Deferred design for optional 24/7 VPS deployment |
| [AGENTS.md](AGENTS.md) | The sprint loop and working agreement for agents and contributors |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and conventions |
| [SECURITY.md](SECURITY.md) | How to report security issues |
| [docs/](docs) | ADRs, sprint plans, risk register, verification checklists, version matrix |

## Repository layout

```text
trend-setter/
├── apps/desktop/          # Electron + React shell (from Sprint 1 desktop work)
├── engine/                # Python trading engine (package: trendbot)
│   ├── src/trendbot/      # api, application, config, database, exchange,
│   │                      # market_data, strategies, risk, execution,
│   │                      # backtesting, paper, observability
│   └── tests/
├── docs/
│   ├── adr/               # Architecture decision records
│   ├── sprints/           # Sprint plans and outcomes
│   ├── risk-register.md
│   ├── coinbase-verification-checklist.md
│   └── version-matrix.md
├── scripts/               # Repo hygiene and dev scripts
├── architecture.md        # Master architecture (baseline)
├── implementation.md      # Engineering conventions
├── sprint-roadmap.md      # Sprint plan (source of truth for sequencing)
└── vps-deployment.md      # Deferred VPS deployment design
```

## Sprint status

| Roadmap sprint | Focus | Status |
|---|---|---|
| 0 | Architecture lock, Coinbase verification, risk register | **Done** — all 8 items verified against official docs |
| 1 | Repo, dev environment, application skeleton | **Done** — desktop shell, engine loopback API, supervisor, fake adapter |
| 2 | Database foundation, migrations, durable events | **Done** — 16 core tables, Alembic, repositories, backup/restore |
| 3 | Coinbase connection wizard and secure credentials | **Done** — OS-backed secret store, JWT validation, wizard UI (real-key test pending) |
| 4 | Historical market data and candle correctness | **Done** — windowed imports, validation, dedup, gaps, aggregation; live-API verified |
| 5 | Live market data, reconnect, and backfill | **Done** — WS feed, heartbeats, reconnect, backfill, stale gate |
| 6 | Baseline strategy and configuration | **Done** — EMA/RSI indicators, crossover decisions, versioned config, persisted signals |
| 7 | Backtesting engine and evaluation UI | **Done** — fee-aware simulations, OOS split, labeled metrics |
| 8 | Risk manager and order lifecycle (mock exchange) | **Done** — risk gate, durable intents, timeout recovery, reconciliation |
| 9 | Paper trading | Next |
| 4–14 | Historical data → live data → strategy → backtest → risk → paper → live → packaging → audit | Not started |

Progress details in [docs/sprints/](docs/sprints).

## Development quickstart

(Windows, Git Bash; full details in [CONTRIBUTING.md](CONTRIBUTING.md))

```bash
python -m venv .venv
source .venv/Scripts/activate          # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e "engine[dev]"

cd engine
python -m pytest                       # unit tests
python -m ruff check .                 # lint
cd ..
python scripts/repo_checks.py          # secret scan + docs hygiene
```

No API keys are needed for development; automated tests use a mock exchange only.

## Safety by design

- **Paper-first:** default mode is paper; live trading requires explicit arming and never auto-resumes.
- **Risk gate:** every order intent passes a mandatory risk manager; strategy code cannot submit orders.
- **Least privilege:** no withdrawal/transfer capability exists or will be requested from Coinbase.
- **Secrets stay local:** OS credential store only — never in the repo, logs, or diagnostics.

## License

[MIT](LICENSE)
