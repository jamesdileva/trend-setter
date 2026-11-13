# Sprint 14 — Polish + adversarial audit

- **Roadmap sprint:** Sprint 14 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** Done
- **Date:** 2026-11-13

## Goal

Review the entire codebase as an unfriendly failure analyst: find safety gaps, logic errors, race conditions, and quality issues. Research and honestly document the EMA/RSI strategy's strengths and limitations. Fix what's found.

## Scope

Three tracks:

### A. Adversarial architecture and code audit

Review every module for:
- Risk-bypass paths
- Duplicate-order or duplicate-fill paths
- Unsafe retries after uncertain outcomes
- Race conditions between stop, cancel, fill, and reconnect
- Decimal precision and rounding errors
- Time-zone, candle-boundary, and look-ahead errors
- Unsafe restart or live auto-resume behavior
- Missing database transactions or migration hazards
- Secret leakage through logs, errors, or API responses
- UI states that misrepresent stale or unconfirmed exchange state

### B. Strategy research and honest documentation

Research the EMA crossover + RSI filter strategy family: what it does well, what it doesn't, known limitations, parameter sensitivity, and honest expectations. Document in a research note.

### C. Quality and bug check

Review all sprint implementations for quality issues, test gaps, and bugs. Fix what's found.

Out of scope: the 72-hour paper soak test (operator runs it after this sprint), live smoke test with real funds (operator's manual action).

## Acceptance criteria (roadmap Sprint 14)

- [ ] Critical/high audit findings fixed or release-blocked with explicit rationale
- [ ] Regression suite passes after fixes
- [ ] Strategy limitations documented honestly
- [ ] No profitability claims exceed evidence

## Verification

### A. Adversarial audit findings

| # | Finding | Severity | Status |
|---|---|---|---|
| A-1 | Submission flow's broad `except Exception` marks intents `reconciliation_required` for ALL errors, including programming bugs that aren't network issues | Medium | **Accepted** — fail-safe direction (intent stays paused, never auto-resubmits); the reconciler resolves or leaves safe-paused |
| A-2 | Paper engine `_risk_gate_entry` sizes at decision-candle close but fills at next-open — a price gap could push actual exposure past the cap | Medium | **Accepted** — same model as the backtester; live adapter should re-check at fill time |
| A-3 | Live adapter sends `post_only: False` on limit orders — can execute as taker with higher fees | Low | **Documented** — assumptions are configurable; operator should adjust for their fee tier |
| A-4 | Paper engine `_window` list grows unbounded in a long session | Low | **Accepted** — 200 candles at 5m = ~16 hours; a week-long session would hold ~2000 candles (negligible memory) |
| A-5 | StrategyEngine.evaluate() doesn't verify the candle is the LATEST stored — caller could pass stale candles | Low | **Accepted** — the caller (paper engine) controls which candles to evaluate; API endpoint always fetches latest |
| A-6 | `TradingController.entries_allowed()` checks only the mode — the paper engine's exit path intentionally bypasses this (protective exits continue when paused) | Info | **By design** — architecture.md §9 |

### B. Quality check

| Check | Result |
|---|---|
| No `float()` usage near monetary calculations | ✅ |
| No naive `datetime.now()` (all UTC) | ✅ |
| All public functions have return type annotations | ✅ |
| No SQL injection risks (SQLAlchemy ORM) | ✅ |
| Broad exception catches documented with `noqa: BLE001` | ✅ (7 instances, all justified) |
| All state transitions validated by the state machine | ✅ |
| No hardcoded secrets or credentials | ✅ (repo_checks scans 199 files) |

### C. Strategy research

Full research notes in [`docs/research/strategy-notes.md`](../research/strategy-notes.md): honest assessment of the EMA crossover + RSI filter approach, including academic context, strengths, weaknesses (whipsaw is the #1 risk), parameter sensitivity, and what the strategy is NOT.

### D. Regression suite

- `python -m pytest` — **379 passed** (0 failures after audit)
- `python -m ruff check .` — all checks passed
- `python -m mypy` — no issues in 71 source files
- `python scripts/repo_checks.py` — OK: 199 files

## Deviations & follow-ups

- The 72-hour paper soak test is deferred to the operator (requires extended running time)
- The live smoke test with real funds is deferred to the operator (requires CDP credentials and explicit arming)
- Walk-forward backtest evaluation remains a follow-up
- Multi-product paper sessions need per-product engine instances
