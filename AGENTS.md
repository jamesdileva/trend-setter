# AGENTS.md — How we work in this repository

This project is built one sprint at a time from [`sprint-roadmap.md`](sprint-roadmap.md).
This file is the binding working agreement for AI agents and human contributors: follow it for every change you make.

## Source of truth

| Document | Read it for |
|---|---|
| [`sprint-roadmap.md`](sprint-roadmap.md) | What to build next: sprint scope, tasks, verification, exit criteria |
| [`architecture.md`](architecture.md) | System design, non-negotiable design rules, component boundaries |
| [`implementation.md`](implementation.md) | Code organization, layering, engineering conventions |
| [`docs/adr/`](docs/adr) | Recorded decisions that refine or change the baseline architecture |
| [`docs/risk-register.md`](docs/risk-register.md) | Known risks and their mitigations |

**Precedence:** the sprint roadmap decides sequencing; the architecture decides design. If a change would contradict `architecture.md`, do not silently deviate — record an ADR (see `docs/adr/`) or update the architecture doc first.

## The sprint loop

Every sprint (and every meaningful change) follows the same loop:

1. **Plan & scope.** Read the current sprint in `sprint-roadmap.md` (goals, tasks, verification, exit criteria). Restate the goal in one sentence, list the exact files to create or change, and name the acceptance criteria you will verify. Write this into `docs/sprints/sprint-NN-<slug>.md` (start from `docs/sprints/sprint-plan-template.md`). If scope is ambiguous or touches live trading, confirm with the user before implementing.
2. **Implement.** Make the smallest change that completes the scope. Inspect existing files before changing them; preserve working functionality. Prefer small, explicit modules. Follow the layering rules in `implementation.md` §2 (module ownership table).
3. **Verify.** Run the focused tests for what changed, then the full relevant suite, lint, and repo checks (commands below). Everything must pass before committing. A safety-critical test failure stops work — do not commit around it.
4. **Commit & push.** Use Conventional Commits (below). Push to `origin`. CI must be green on `main`.
5. **Report & close.** State what changed, what was tested, and what remains. Fill in the "Verification" and "Deviations" sections of the sprint doc. Record any deviation from the roadmap in the sprint doc — never silently.

### Session start checklist

- `git pull` and confirm `main` is green before starting.
- Re-read the current sprint section in `sprint-roadmap.md`.
- Confirm the baseline commands still pass before building on top.

## Commands

Windows (Git Bash) from the repository root:

```bash
# One-time setup
python -m venv .venv
source .venv/Scripts/activate        # cmd: .venv\Scripts\activate.bat | PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "engine[dev]"

# Verify (run in this order)
cd engine
python -m pytest                     # engine unit tests
python -m ruff check .               # lint
cd ..
python scripts/repo_checks.py        # secret scan + docs/link hygiene
```

CI runs the same checks (`.github/workflows/ci.yml`). The `engine` CI job activates automatically as soon as Python files exist under `engine/`.

## Commit conventions

- Format: `type(scope): summary in imperative mood` — e.g. `feat(engine): persist order intents`, `fix(risk): round position size down to increment`.
- Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `ci`, `build`. Scopes: `engine`, `desktop`, `docs`, `scripts`, `ci`, `repo`.
- One logical change per commit. Tests belong in the same commit as the code they cover.
- Branches for anything risky or multi-step: `sprint-NN/topic`, merged by PR (squash). Small verified sprints may commit directly to `main`; `main` must always be green.

## Non-negotiables

Restated from `architecture.md`; the doc is authoritative.

- **No real orders from automated tests.** Tests use the mock/fake exchange adapter only. Real-exchange smoke tests are manual, separate, and explicitly authorized.
- **Live trading stays disarmed by default.** Nothing may auto-arm or auto-resume live trading after restart, crash, or update.
- **No secrets in the repo, logs, diagnostics, or error messages.** Credentials belong in the OS credential store; `.gitignore` and `scripts/repo_checks.py` enforce the repo part.
- **Money and quantities use `Decimal`** (never binary float); timestamps are UTC internally.
- **Strategies decide; they never execute.** Strategy code cannot submit orders and must not import `exchange/` or `execution/` modules. Every order intent passes the risk manager.
- **Exchange state wins.** Local state reconciles against Coinbase before live execution resumes.

## Code conventions

- Python: `ruff` for lint; type hints on public functions; plain-language error messages (this app serves a nontechnical user).
- Prefer explicit typed models over loose dicts at layer boundaries.
- Every feature ships with tests proportional to its risk; risk and execution code needs thorough state-transition tests (see `implementation.md` §9).
- Update docs (README, sprint doc, ADR when a decision changed) in the same change as the behavior.

## Definition of done

A change is complete only when `implementation.md` §17 holds: correct layer, explicit contracts, appropriate tests, error/recovery behavior, redacted logs, updated docs, existing functionality intact, and the sprint's acceptance criteria passing.
