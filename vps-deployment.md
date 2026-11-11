# Coinbase Automated Trend-Follower — VPS Deployment Addendum

**Document:** `vps-deployment.md`  
**Status:** Deferred deployment design  
**Companion documents:** `architecture.md`, `sprint-roadmap.md`, `implementation.md`  
**Scope:** Optional 24/7 hosted deployment for a nontechnical user without a personal computer

---

## 1. Purpose and relationship to the existing architecture

The initial product remains a Windows 10/11 desktop application that can be installed and run locally. This document defines a **deferred deployment path** for a second operating mode: running the trading engine continuously on a paid Linux VPS.

The VPS path is an additional deployment target, not a replacement for the local application and not a reason to redesign the initial release prematurely.

The intended user experience is:

1. The friend rents a supported VPS plan.
2. The deployment is installed and configured through a guided setup process, ideally with a one-time administrator-assisted setup.
3. The trading engine runs on the VPS as a managed background service, independent of the user's phone or browser being open.
4. The friend opens a secure dashboard from a phone, tablet, or another computer to view status and make permitted configuration changes.
5. If the device used to view the dashboard is turned off or disconnected, the VPS engine continues operating.

**Important distinction:** A VPS provides an always-on computer in a data center. It does not guarantee profitable trading, uninterrupted exchange connectivity, or zero downtime. The application must make failures visible and recover safely.

## 2. Deferred scope and non-goals

### Included in this deferred feature

- Linux VPS deployment, initially targeting a current Ubuntu LTS release.
- Headless Python engine operation without Electron or a desktop session.
- Service manager integration so the engine starts on boot and restarts after recoverable process failures.
- Persistent storage for configuration, market data, orders, fills, events, and audit history.
- Secure Coinbase credential provisioning and storage on the VPS.
- Remote dashboard access from a browser, including mobile-sized layouts.
- Secure remote access, preferably through a private VPN such as Tailscale or WireGuard.
- Health checks, log access, disk monitoring, backups, and alerting.
- Documented upgrade, rollback, restore, pause, and shutdown procedures.
- A repeatable deployment process, preferably automated after the first manually verified implementation.

### Explicitly not included in the initial Windows release

- Mandatory cloud hosting.
- A public multi-tenant SaaS platform.
- Public signup, billing, or user management.
- Exposing the trading control API directly to the public internet.
- Remote trading controls without authentication, authorization, and audit logging.
- Automatic deployment of unreviewed application updates.
- High-availability clustering or multi-region failover.

## 3. Recommended deployment architecture

The cleanest long-term design is to separate the trading engine from the desktop shell. The engine should already be independently runnable and controlled through a narrow application interface. The VPS deployment then runs that same engine in headless mode.

```text
                    FRIEND'S PHONE / TABLET
                              |
                        Private VPN
                    (Tailscale/WireGuard)
                              |
                              v
+----------------------------------------------------------+
|                         LINUX VPS                        |
|                                                          |
|  +--------------------+     +--------------------------+ |
|  | Browser Dashboard  |<--->| Authenticated API        | |
|  | Responsive Web UI  |     | Read + permitted controls| |
|  +--------------------+     +------------+-------------+ |
|                                           |              |
|                                +----------v-----------+  |
|                                | Application Service  |  |
|                                | Headless Python      |  |
|                                | Trading Engine       |  |
|                                +----------+-----------+  |
|                                           |              |
|      +------------------+-----------------+-----------+  |
|      |                  |                 |           |  |
|  +---v------+    +------v------+   +------v------+ +--v--+
|  | Strategy |    | Risk Manager|   | Execution   | | Data|
|  | Engine   |    | + Kill Switch|  | + Reconcile | |Store|
|  +----------+    +-------------+   +------+------+ +-----+
|                                           |              |
|                                  Encrypted credentials   |
|                                  Persistent database     |
|                                  Logs + backups          |
+-------------------------------------------+--------------+
                                            |
                                   Outbound HTTPS/WSS
                                            |
                                     COINBASE API
```

### Architectural rule

The dashboard is a client of the application API. It must never connect directly to Coinbase trading endpoints or hold Coinbase private keys. All order decisions and exchange actions remain inside the engine and must pass through the same risk manager and execution state machine used by local mode.

## 4. Deployment modes

The application should support two deployment profiles without forking core trading logic.

| Concern | Local Windows mode | VPS mode |
|---|---|---|
| Engine | Local background process | Linux managed service |
| User interface | Electron desktop app | Responsive browser dashboard |
| Database | Local SQLite initially | SQLite initially for single-instance use; reassess PostgreSQL if scale/concurrency requires it |
| Credentials | Windows Credential Manager / DPAPI | Linux secret file with strict permissions or supported secret manager |
| Startup | Desktop supervisor / optional startup setting | systemd service |
| Access | Local machine | Private VPN by default |
| Updates | Installer-driven | Controlled deployment and rollback |
| Availability | Depends on PC and power | Depends on VPS provider and network |
| User device may be off | No, if engine is tied to that PC | Yes; VPS keeps running |

The local and VPS deployments must use the same strategy, risk, order, and reconciliation modules. Deployment-specific code belongs in adapters and configuration, not in duplicated trading logic.

## 5. VPS sizing and operating-system assumptions

Start with a modest single-instance VPS rather than over-provisioning. The workload is expected to be light for two spot-market products and a small number of candle intervals, but actual sizing must be measured under realistic logging, data retention, and backtesting conditions.

### Initial planning baseline

- Linux: current Ubuntu LTS, 64-bit.
- CPU: 1–2 vCPU as an initial test target.
- RAM: 2 GB minimum test target; 4 GB preferred starting point if affordable.
- Storage: SSD-backed storage with enough headroom for the database, logs, backups, and historical candles.
- Network: stable outbound HTTPS and WebSocket connectivity.
- Region: choose a reputable provider and a region with reliable connectivity to Coinbase services; do not assume geographic proximity guarantees low latency or better execution.
- Time: system clock synchronized using standard time synchronization.
- Access: SSH for administration, restricted to key-based access; no password-based root login.

These are provisional sizing targets, not vendor requirements. Benchmark the actual application before selecting a paid plan. Avoid purchasing a large VPS before memory, CPU, disk growth, and network behavior are measured.

## 6. Service lifecycle and restart behavior

Use `systemd` to manage the headless application service.

Required behavior:

1. Start after the operating system has completed basic network initialization.
2. Run under a dedicated unprivileged service account.
3. Restart after an unexpected process exit using a bounded restart policy.
4. Expose a health endpoint or local health command for monitoring.
5. Stop gracefully on service shutdown and host maintenance.
6. Persist all order intents and state transitions before external side effects.
7. On every startup, enter a recovery/reconciliation phase before any live order can be submitted.
8. Never interpret a process restart as permission to resume live trading.
9. If reconciliation cannot complete, remain in a safe paused state and alert the user.
10. Support a deliberate maintenance mode that prevents new entries while allowing safe cancellation or position-management behavior defined by policy.

A service manager restart is not a trading recovery strategy. The engine must independently implement safe recovery, duplicate-order prevention, and exchange reconciliation.

### Startup state machine

```text
SERVICE START
     |
     v
Load configuration and secret references
     |
     v
Validate database + migrations + clock
     |
     v
Connect to Coinbase (read/reconcile)
     |
     v
Reconcile balances, open orders, fills, positions
     |
     +---- failure / uncertainty ----> PAUSED + ALERT
     |
     v
Validate risk limits and live-trading arming state
     |
     +---- not explicitly armed ------> PAPER / PAUSED
     |
     v
Begin permitted operation
```

## 7. Remote dashboard and access security

### Recommended default: private VPN

For a single nontechnical user, use a private VPN overlay such as Tailscale or a carefully configured WireGuard network. The dashboard and API should bind to the VPN interface or remain behind a local reverse proxy reachable only through the VPN.

Benefits:
- No public dashboard port needs to be exposed.
- The user can access the dashboard from a phone or tablet.
- Access can be revoked through the VPN provider or server configuration.
- The application can avoid building a public internet-facing identity platform for a single-user deployment.

The VPN is an access layer, not a substitute for application authorization. The dashboard/API must still require authentication and enforce permissions.

### If public internet access is ever required

Treat it as a separate security project. At minimum it requires:
- HTTPS with correctly managed certificates.
- Strong authentication and session expiry.
- Rate limiting and login abuse protection.
- CSRF protection where cookie-based sessions are used.
- Secure cookies and appropriate browser security headers.
- Authorization checks on every control endpoint.
- Audit logging for every configuration or trading-control action.
- Secret redaction and safe error responses.
- Regular operating-system and dependency updates.
- Independent security review before production use.

Do not expose the raw FastAPI engine control interface to the public internet.

### API boundaries

Separate read-only dashboard endpoints from control endpoints. Examples:

**Read-only**
- Engine status and last heartbeat.
- Current mode and live-arming state.
- Balances, positions, open orders, fills, and trade history.
- Strategy configuration and active timeframe.
- Recent signals, risk decisions, health events, and logs.

**Control actions requiring authorization and audit**
- Pause new entries.
- Resume operation after checks.
- Request graceful stop.
- Change strategy parameters.
- Change risk limits.
- Arm or disarm live trading.
- Cancel an order where supported by the safety policy.

Sensitive actions should require confirmation and, for live trading activation or risk-limit reductions, a deliberate second confirmation. The UI must clearly identify whether an action affects paper or live mode.

## 8. Coinbase credentials on the VPS

The Windows Credential Manager design does not directly transfer to Linux. Implement a platform-neutral credential-provider interface with separate Windows and Linux implementations.

For VPS mode:
- Create a dedicated service account.
- Store the Coinbase key material outside the application repository and outside the web root.
- Restrict secret-file ownership and permissions to the service account.
- Never put secrets in command-line arguments, URLs, logs, crash reports, database rows, or dashboard responses.
- Prefer a supported secret manager if the selected VPS environment provides one and the operational complexity is justified.
- Provide a guided credential setup flow or a one-time secure provisioning command that does not echo the private key.
- Support key replacement and revocation.
- Keep Coinbase permissions to the minimum needed; do not request withdrawal or transfer permissions.
- Use Coinbase IP allowlisting if available for the selected key/account configuration, and verify its behavior before relying on it.
- Document how to revoke the key immediately if the VPS is compromised.

The dashboard should show credential status and last successful validation, never the private key itself.

## 9. Persistence, backup, and recovery

The first VPS deployment can continue using SQLite if the application remains a single engine instance with controlled database writes. SQLite is not automatically unsuitable for a small VPS deployment, but concurrency and backup behavior must be explicitly tested.

Requirements:
- Keep the database on persistent VPS storage, not an ephemeral container filesystem.
- Use a supported SQLite backup mechanism or a consistent application-level backup process.
- Back up configuration and operational records without copying private keys into ordinary backups.
- Encrypt backups before transferring them off the VPS.
- Retain multiple dated backups and monitor backup success.
- Test restore into a clean environment.
- Monitor disk usage and log rotation.
- Define retention for raw market data, logs, and diagnostic bundles.
- Do not delete order, fill, or audit history merely to reduce database size.
- Document provider snapshots as an additional recovery layer, not the only backup.

A restore must not cause old order intents to be replayed. After restore, the engine must reconcile with Coinbase and require a safe explicit resume decision.

## 10. Monitoring and notifications

A 24/7 deployment needs useful alerts because the user may not be watching the dashboard.

Minimum health monitoring:
- Engine heartbeat and service state.
- Last successful Coinbase market-data update.
- Last successful account/order reconciliation.
- API connectivity failures and rate limiting.
- Database write failures and integrity status.
- Disk space and memory pressure.
- Unexpected process restarts.
- Backup completion and restore-test status.
- Trading pause, kill-switch, and risk-limit events.
- Open-order age and unresolved order states.

Notifications can be a later increment. Start with email or another explicitly selected provider only after the core health-event model exists. Notifications must never include API private keys, authentication tokens, or other secrets.

An alert is not proof that the engine has safely stopped. The UI and notification must distinguish:
- service unavailable,
- engine paused,
- new entries disabled,
- live mode disarmed,
- open orders still requiring reconciliation.

## 11. Deployment and update strategy

Do not make the first deployment depend on a complicated orchestration stack. A single VPS and a documented deployment script are sufficient for the first version.

Recommended progression:

1. Manually deploy a test build to a disposable VPS.
2. Verify headless startup, API connectivity, persistence, and recovery.
3. Run paper mode continuously for an extended observation period.
4. Test reboot, network loss, Coinbase API failure, disk pressure, and process termination.
5. Add a repeatable deployment script.
6. Add versioned releases and pre-upgrade database backups.
7. Add rollback to the previous application version.
8. Only then consider containerization or more elaborate orchestration if it materially improves reproducibility.

Docker Compose may be evaluated as a packaging option, but it is not mandatory. If used, secrets must not be embedded in images or committed Compose files, and persistent volumes and restart/recovery behavior must be tested.

### Update rules

- Never silently update the live trading engine.
- Display the current version and available update.
- Require the engine to enter a safe maintenance state before updating.
- Back up the database and non-secret configuration.
- Apply migrations with a verified rollback/recovery plan.
- Restart into reconciliation mode.
- Require an explicit resume decision if live mode was previously armed.
- Keep the prior known-good release available for rollback.

## 12. Deferred implementation phases

These phases are intentionally outside the initial Windows roadmap. They should be scheduled only after the local application is stable and the engine can run independently of Electron.

### VPS Phase A — Headless engine readiness

**Goal:** Prove the existing engine can run without a desktop UI.

Tasks:
- Remove desktop-shell assumptions from engine startup.
- Add explicit headless configuration.
- Add service health and readiness checks.
- Ensure all core operations use the same application services as local mode.
- Verify clean shutdown and restart recovery.

Exit criteria:
- Engine runs headlessly on a development Linux environment.
- No strategy or execution logic is duplicated.
- Startup always reconciles before live operation.

### VPS Phase B — Linux service deployment

**Goal:** Install and operate the engine as a managed VPS service.

Tasks:
- Select and document a supported Ubuntu LTS baseline.
- Create a dedicated service account and directory layout.
- Add systemd unit and deployment scripts.
- Add log rotation, time synchronization checks, and disk monitoring.
- Add persistent database and backup procedures.
- Add versioned update and rollback procedures.

Exit criteria:
- Reboot starts the service safely.
- Unexpected process exit is handled.
- Service failure or reconciliation uncertainty leaves trading paused.
- Backup and restore have been tested.

### VPS Phase C — Secure browser dashboard

**Goal:** Let the friend monitor and control the deployment from a phone or browser.

Tasks:
- Build a responsive web dashboard reusing existing React components where practical.
- Add authentication and server-side authorization.
- Separate read-only endpoints from control endpoints.
- Add private VPN deployment instructions.
- Add session management, audit logging, and sensitive-action confirmations.
- Verify the dashboard is not publicly reachable in the default deployment.

Exit criteria:
- User can securely view health, portfolio, orders, fills, and events from a phone.
- Control actions are authenticated, authorized, audited, and mode-aware.
- API keys are never sent to the browser.

### VPS Phase D — 24/7 operational hardening

**Goal:** Validate unattended operation.

Tasks:
- Run a sustained paper-trading soak test.
- Simulate host reboot, network loss, exchange outage, process crash, database error, and full disk.
- Validate alerts and safe-paused states.
- Test backup restore and application rollback.
- Document incident response, key revocation, and VPS replacement.

Exit criteria:
- All failure scenarios have documented expected behavior and passing tests.
- No duplicate orders occur in tested uncertain-outcome scenarios.
- No failure causes automatic unsafe re-arming of live trading.
- The friend has a concise operator guide for normal use and emergencies.

## 13. Acceptance checklist for VPS release

- [ ] VPS deployment is optional; local Windows operation remains supported.
- [ ] Engine runs without Electron or an interactive desktop session.
- [ ] Same strategy, risk, and execution code is used in local and VPS modes.
- [ ] Engine starts on boot through a service manager.
- [ ] Startup reconciliation completes before live execution is permitted.
- [ ] Uncertain exchange state results in a safe pause.
- [ ] Dashboard is reachable through the documented private access method.
- [ ] No unauthenticated public control interface exists.
- [ ] Dashboard does not receive Coinbase private key material.
- [ ] Secrets are stored with restrictive permissions and excluded from backups/logs.
- [ ] Database and backups survive service restart and host reboot.
- [ ] Restore procedure is tested.
- [ ] Disk, memory, heartbeat, API, and backup health are monitored.
- [ ] Updates are deliberate, versioned, backed up, and reversible.
- [ ] Friend-facing setup and emergency instructions are written in plain language.
- [ ] Paper-mode soak test and failure-injection tests pass before any live deployment.

## 14. Important operational and financial considerations

The VPS creates a recurring hosting cost. The user should compare providers based on total monthly cost, persistent storage, backup pricing, bandwidth, region, support, and ease of administration rather than CPU price alone.

The VPS does not eliminate:
- Coinbase downtime or API changes.
- Internet routing failures.
- Exchange rate limits.
- Market gaps, spreads, slippage, or fees.
- Strategy losses.
- Provider maintenance or outages.
- The need to monitor alerts and review account activity.

The friend should retain direct access to Coinbase and understand how to revoke the API key and disable trading independently of this application.

**Deployment recommendation:** Keep the first release local-first. Build the engine so it can be run headlessly, but defer VPS deployment, remote dashboard, and 24/7 operational hardening until local paper trading, reconciliation, risk controls, and recovery have been proven.
