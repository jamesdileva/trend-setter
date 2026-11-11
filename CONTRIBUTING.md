# Contributing

Thanks for helping build trend-setter. Read [AGENTS.md](AGENTS.md) first — it defines the sprint loop, commit conventions, and the safety non-negotiables that apply to every change.

## Setup (Windows)

1. Install Python 3.11+ (CI pins 3.14) and, once desktop work starts, Node (CI pins 24).
2. Clone the repo, then from the repo root:

```bash
python -m venv .venv
source .venv/Scripts/activate        # cmd: .venv\Scripts\activate.bat | PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "engine[dev]"
```

3. Verify your environment:

```bash
cd engine && python -m pytest && python -m ruff check . && cd ..
python scripts/repo_checks.py
```

## Before you push (or open a PR)

- Tests, lint, and `scripts/repo_checks.py` pass locally.
- New behavior has tests; existing tests still pass.
- Docs are updated (sprint doc, README, ADR when a decision changed).
- Commit messages follow Conventional Commits (see [AGENTS.md](AGENTS.md)).
- Nothing secret is committed — no `.env`, keys, tokens, databases, or logs.

## Reporting problems

- Bugs and feature ideas: GitHub issues (templates provided).
- Security issues: **do not** open a public issue — see [SECURITY.md](SECURITY.md).
