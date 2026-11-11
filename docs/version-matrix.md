# Version Matrix

**Purpose:** record pinned tool/runtime versions (Sprint 0 deliverable; see [`implementation.md`](../implementation.md) §3). Update whenever a pin changes; CI is the enforced source of truth for CI pins.

| Component | Version | Where pinned | Verified against | Notes |
|---|---|---|---|---|
| Python (engine) | 3.14 | `.github/workflows/ci.yml`; dev machine runs 3.14.3 | Sprint 1 suite (71 tests) passes on 3.14 | architecture requires 3.11+ |
| Node (desktop) | 24 | `.github/workflows/ci.yml`; dev machine runs 24.14.1 | Sprint 1 typecheck + vitest pass on 24 | |
| Engine runtime deps | fastapi 0.162.4, uvicorn 0.54.0, sqlalchemy 2.1.8, alembic 1.20.1 (pydantic 2.14.3) | `engine/pyproject.toml` ranges | Sprint 1–2 suites | widen only with the full suite passing |
| Engine dev deps | pytest 9.2.0, ruff 0.17.4, mypy 2.4.1, httpx 0.28.1 | `engine/pyproject.toml` `[dev]` | — | type checks enforced in CI |
| Desktop deps | electron 37.10.3, vite 6.4.6, react 19.3.1, typescript 5.9.3, vitest 3.2.7 | `apps/desktop/package.json` + committed `package-lock.json` | Sprint 1 build/typecheck/vitest | lockfile is the source of truth |
| Windows target | 10/11 x64 | architecture.md §17 | — | installer testing on clean VMs is a later sprint |

## Rules

- Runtime dependencies are pinned and kept minimal.
- Dev tooling lives in the `dev` extra, never runtime.
- Upgrade the Python/Node minor version only after the full suite passes on it.
