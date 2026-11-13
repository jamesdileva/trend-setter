# Sprint 12 — Windows packaging, installer, and lifecycle

- **Roadmap sprint:** Sprint 12 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-12

## Goal

Deliver a double-click Windows installer that bundles the Electron dashboard and the PyInstaller-compiled engine executable, with Start Menu/desktop shortcuts, NSIS uninstall, and app-data directory management.

## Scope

- `build/engine.spec` — PyInstaller spec for the engine (SQLAlchemy, Alembic, cryptography, PyJWT, keyring, FastAPI/uvicorn as hidden imports)
- `apps/desktop/electron-builder.yml` — Electron Builder NSIS config (shortcuts, uninstall, app metadata)
- `apps/desktop/package.json` — build scripts and electron-builder dependency
- `scripts/build_installer.py` — end-to-end build script (PyInstaller → Electron Builder → installer .exe)
- Engine executable resolves paths for packaged mode (no venv, no editable install)

Out of scope (deferred): code signing (requires a certificate), clean Windows 10/11 VM testing (manual), update/rollback workflow (future sprint), background-running mode decision.

## Acceptance criteria (roadmap Sprint 12, adapted scope)

- [x] PyInstaller builds a standalone engine executable (onedir, with migrations and alembic.ini bundled)
- [x] Electron Builder produces a Windows NSIS installer (trend-setter-setup-0.1.0.exe, 127 MB)
- [x] The installer bundles the engine executable and migrations (verified in win-unpacked/resources/engine/)
- [x] Start Menu / desktop shortcuts created (NSIS config)
- [x] App data directories created on first launch (existing default_data_dir)
- [x] Packaged engine mode: supervisor uses the bundled engine exe instead of the venv Python
- [x] Clean uninstall documented (NSIS deleteAppDataOnUninstall=false — user data is preserved)

## Verification

- `python -m PyInstaller ../build/engine.spec` → dist/trendbot-engine/ with engine exe, migrations, alembic.ini
- Engine exe tested: `TRENDBOT_LOCAL_TOKEN=pyi-test dist/trendbot-engine/trendbot-engine.exe --port 8790` → health 200, migrations applied
- `npx electron-builder --win` → release/trend-setter-setup-0.1.0.exe (127 MB) with engine bundled in resources
- `npm run typecheck && npm test` — clean; 11 passed

## Deviations & follow-ups

- Code signing not configured (requires a certificate; documented deferred)
- Clean Windows 10/11 VM testing is a manual task for the operator
- Update/rollback workflow deferred to a later sprint
- Background-running mode (engine continues when dashboard closes) is a deliberate decision deferred to the operator
- The market data chart's "Failed to load data" issue is resolved by restarting the engine (the chart endpoint was added after the engine was last started). This is a known issue when adding new API endpoints to a running engine.
