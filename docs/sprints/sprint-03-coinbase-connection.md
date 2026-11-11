# Sprint 03 — Coinbase connection wizard and secure credentials

- **Roadmap sprint:** Sprint 3 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** In progress
- **Date:** 2026-11-11

## Goal

Make connecting Coinbase approachable for a nontechnical user without exposing secrets: guided wizard, OS-backed secret storage, credential validation with a non-trading request, and replace/disconnect flows — all built and verified offline.

## Scope

Engine (`engine/`):

- `src/trendbot/security/secret_store.py` — platform-neutral `SecretStore` interface (implementation.md §12); Windows implementation uses **Windows Credential Manager via the `keyring` library** (ADR-0002); in-memory implementation for tests/dev on other platforms
- `src/trendbot/config/paths.py` — default app-data directory (`%LOCALAPPDATA%/trend-setter`)
- `src/trendbot/exchange/coinbase_auth.py` — ES256 JWT builder per the Sprint 0 verified spec (kid/sub = key name, `iss: cdp`, `nbf`/`exp` = 120 s, header nonce, REST `uri` claim)
- `src/trendbot/exchange/coinbase_rest.py` — narrow validation client: `GET /accounts` (view) as the non-trading probe; **trade-permission probe via empty `batch_cancel`** (non-trading: cancels nothing); typed error classification — invalid credentials, insufficient permissions, network unavailable, unexpected exchange state; rejects non-ECDSA keys with plain ECDSA/Ed25519 guidance
- `src/trendbot/application/coinbase_connection.py` — connect/status/retest/disconnect service: secret only ever in the OS store; metadata (`credential_metadata` table) holds key reference, status, permissions, last-validated time; single active credential per provider
- `src/trendbot/api/app.py` + `src/trendbot/api/schemas.py` — token-gated endpoints: `POST /coinbase/credentials`, `GET /coinbase/connection`, `POST /coinbase/test-connection`, `POST /coinbase/disconnect`, `GET /diagnostics` (redacted); shared token dependency; explicit DI of database + secret store
- `main.py` — engine boots against the real app-data database (Sprint 2 migrations + pre-migration backups) and wires the platform secret store
- deps: `keyring`, `cryptography`, `pyjwt` (runtime); `httpx` moves from dev to runtime

Desktop (`apps/desktop/`):

- `electron/urls.ts` + vitest — strict allowlist for opening external URLs (official Coinbase domains, https only)
- `electron/main.ts` + `preload.ts` — IPC for the wizard; **the session token never reaches the renderer**: the main process performs engine requests via a new `EngineSupervisor.engineRequest()`; credentials pass renderer → main → engine once and are never stored renderer-side
- `src/components/ConnectionCard.tsx` — plain-language wizard: why we need access, opens the official key page, **explicit ECDSA instruction** (portal defaults to Ed25519 — Sprint 0 finding), View-only guidance, never Transfer; secure inputs (masked), Save & test, Retest, Disconnect; classified plain-language errors (implementation.md §16 wording)

Explicitly out of scope: full market-data adapter (Sprint 4), live trading, real-key testing (needs the user's own Coinbase account + CDP key; all automated tests use generated keys and mocked responses — no test places an order, and no order endpoint exists).

## Acceptance criteria (roadmap Sprint 3 verification)

- [x] Invalid key fails with actionable, plain-language instructions (401 → "copied exactly" + ECDSA/Ed25519 guidance; Ed25519 keys rejected with the same guidance before any request)
- [x] Valid read-only key passes data/account validation (verified offline against documented response shapes; real-key pass pending the user's manual test)
- [x] Live-trading permission is separately detected (empty `batch_cancel` probe — cancels nothing; 401→inconclusive, 403→absent, other→present)
- [x] Secret is not found in SQLite, config files, logs, diagnostics, or API responses (byte-level DB scan + JSON assertions on every response)
- [x] Disconnect removes the stored credential reference and secret (store delete + metadata delete, verified)
- [x] No test places an order (only trading-path call is the empty cancel probe; no order endpoint exists)

## Verification

Commands and results (Python 3.14.3, Node 24.14.1):

- `python -m pytest` (in `engine/`) — **123 passed** (+35: JWT spec/verification tests on generated EC keys, client classification fixtures, connection endpoint flows including secret-leak guards)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 29 source files
- `npm run typecheck` / `npm test` (in `apps/desktop/`) — clean; **11 passed** (+7: URL allowlist incl. lookalike hosts and scheme attacks, token-safe engine request serialization)
- `npm run build` — clean build
- `python scripts/repo_checks.py` — OK: 93 files scanned (two PEM-format false positives resolved: docstring reworded, UI placeholder split)
- Live boot smoke: engine migrated a fresh app-data database on startup; `/health` ok; `/coinbase/connection` → `{connected:false}` with token, **401 without token**; `/diagnostics` redacted (no key material, no event bodies)

## Deviations & follow-ups

- The trade-permission probe is a heuristic: an empty `batch_cancel` cancels nothing, and any non-401/403 outcome is read as "reached a trade-scoped endpoint". Exact real-API behavior (and the `DUPLICATE_CLIENT_ORDER_ID`-style nuances) gets confirmed during the user's manual real-key test and Sprint 10.
- `WindowsCredentialManagerSecretStore` is deliberately **not** touched by automated tests (it would write to the real logged-in user's credential store). It is exercised manually when the user connects their real key (ADR-0002); automated coverage uses the in-memory store.
- Diagnostics intentionally omit event message/detail bodies (type, component, timestamp only) — the most conservative redaction until a redaction layer exists.
- Wizard screenshots are deferred (roadmap task 3: only after confirming the current Coinbase portal UI) — the wizard text is written from the Sprint 0 verified docs and warns about the ECDSA/Ed25519 default.
- Follow-up for Sprint 4/5: the `CoinbaseRestClient` grows into the full market-data adapter; the JWT builder is shared per-request/per-message per the verified spec.
