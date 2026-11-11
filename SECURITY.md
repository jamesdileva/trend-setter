# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security tab → Report a vulnerability**. Do not open a public issue or discuss exploit details publicly.

Include what is affected, how to reproduce, and the impact. If you found a way to leak credentials, place duplicate orders, or bypass the risk manager, say so explicitly — those are the highest-value classes of defect in this project.

Do not include real API keys, credentials, or account identifiers in any report.

## Scope

In scope:

- Credential leakage via the repo, logs, diagnostics, crash reports, or the local API.
- Paths that duplicate orders/fills or bypass the mandatory risk manager.
- Live trading arming or resuming without explicit user action.
- Local API exposure beyond loopback, weak IPC authentication, input-validation gaps.
- Stale or incomplete market data driving trading decisions.

Not yet in scope (not implemented): VPS deployment, remote dashboard, auto-update pipeline — see [vps-deployment.md](vps-deployment.md).

## Supported versions

Only the latest `main` branch is supported.

## Project security stance

- Secrets belong in the OS credential store, never in the repo, logs, or diagnostics.
- Automated tests never place real orders.
- No withdrawal/transfer capability exists in this application by design.
