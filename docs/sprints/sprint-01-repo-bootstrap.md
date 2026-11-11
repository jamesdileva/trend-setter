# Sprint 01 — Repository bootstrap and best-practice scaffolding

- **Roadmap sprint:** first slice of Sprint 1 (repository, test runner, CI); also creates the Sprint 0 doc artifacts (risk register, verification checklist, version matrix, ADRs)
- **Status:** Done
- **Date:** 2026-11-11

## Goal

Stand up the repository workflow (AGENTS.md sprint loop, CI, conventions) and a minimal, tested engine package so every later sprint can follow plan → implement → verify → commit → push.

## Scope

- Root: `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `LICENSE` (MIT), `SECURITY.md`, `.gitignore`, `.editorconfig`, `.gitattributes`
- CI: `.github/workflows/ci.yml` (repo checks; engine lint/tests job auto-activates on `engine/**`), PR/issue templates, `CODEOWNERS`
- Docs artifacts: `docs/adr/` (process + template + ADR-0001), `docs/risk-register.md`, `docs/coinbase-verification-checklist.md`, `docs/version-matrix.md`, `docs/sprints/` (template + this plan)
- Engine skeleton: `engine/pyproject.toml`, `trendbot` package, baseline strategy config model with validation + tests (architecture.md §8 config rules)
- `scripts/repo_checks.py`: secret scan + docs/link hygiene, used locally and in CI

Out of scope: Electron shell, FastAPI loopback API, supervisor, database layer (rest of Sprint 1), any Coinbase integration.

## Acceptance criteria

- [x] Repository initialized (git, `main` branch)
- [x] Engine tests pass on a clean venv
- [x] Lint passes (ruff)
- [x] Repo checks pass (secrets/docs)
- [x] CI green on GitHub after first push
- [x] Public repo created: `jamesdileva/trend-setter`

## Verification

Commands run (Python 3.14.3, fresh `.venv`):

- `python -m pip install -e "engine[dev]"` — clean editable install (trendbot 0.1.0, pytest 9.2.0, ruff 0.17.4)
- `python -m pytest` (in `engine/`) — **46 passed**
- `python -m ruff check .` (in `engine/`) — all checks passed (after fixing 1 E501 and 1 import-order finding)
- `python scripts/repo_checks.py` — OK: 30 files scanned, no secrets, all links and required files present
- CI on GitHub: run [43081630719](https://github.com/jamesdileva/trend-setter/actions/runs/43081630719) — **green** (repo hygiene + engine jobs)

## Deviations & follow-ups

- Roadmap Sprint 0 Coinbase verification items are seeded in [`../coinbase-verification-checklist.md`](../coinbase-verification-checklist.md) but deliberately **not yet verified** — they need official-doc research before the Coinbase integration sprint.
- Remaining Sprint 1 work: Electron + React shell, FastAPI loopback API, supervisor skeleton, shared version/build metadata, fake exchange adapter interface.
- Incident: first CI run (43081208501) failed at startup — GitHub rejects `hashFiles()` in a job-level `if` (workflow parse-time validation). Fix: removed the job gate (`fix(ci)` commit); use step-level `if` when conditional engine testing is needed again.
- Incident: initial push was rejected because the stored Git Credential Manager token lacked the `workflow` scope required to push `.github/workflows/` files. Fix: erased the stale credential; GCM re-authorized with full scopes.
