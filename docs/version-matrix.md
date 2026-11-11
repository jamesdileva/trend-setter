# Version Matrix

**Purpose:** record pinned tool/runtime versions (Sprint 0 deliverable; see [`implementation.md`](../implementation.md) §3). Update whenever a pin changes; CI is the enforced source of truth for CI pins.

| Component | Version | Where pinned | Verified against | Notes |
|---|---|---|---|---|
| Python (engine) | 3.14 | `.github/workflows/ci.yml`; dev machine runs 3.14.3 | — | architecture requires 3.11+; re-verify all engine dependencies on this version before Sprint 2 |
| Node (desktop) | 24 | dev machine runs 24.14.1 | — | pin the exact version when desktop work starts (Sprint 1) |
| Engine dependencies | none yet | `engine/pyproject.toml` | — | keep runtime deps minimal; dev tooling in the `[dev]` extra |
| Desktop dependencies | none yet | `apps/desktop/package.json` + committed lockfile | — | lockfile must be committed |
| Windows target | 10/11 x64 | architecture.md §17 | — | installer testing on clean VMs is a later sprint |

## Rules

- Runtime dependencies are pinned and kept minimal.
- Dev tooling lives in the `dev` extra, never runtime.
- Upgrade the Python/Node minor version only after the full suite passes on it.
