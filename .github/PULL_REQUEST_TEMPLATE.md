## Summary

What and why. Link the sprint plan (e.g. `docs/sprints/sprint-NN-<slug>.md`) and the roadmap sprint it implements.

## Changes

-

## Verification

- [ ] Focused tests for what changed pass
- [ ] Full engine suite passes (`python -m pytest` in `engine/`)
- [ ] Lint passes (`python -m ruff check .` in `engine/`)
- [ ] `python scripts/repo_checks.py` passes
- [ ] CI green

## Safety

- [ ] No secrets or credentials committed
- [ ] Automated tests use the mock exchange only (no real orders possible)
- [ ] Behavior does not contradict `architecture.md` (or an ADR records the change)
- [ ] Docs updated where behavior changed
