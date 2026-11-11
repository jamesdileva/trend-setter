# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

Sprint 0 of [`sprint-roadmap.md`](../../sprint-roadmap.md) requires recording architecture decisions and deviations. [`architecture.md`](../../architecture.md) is the baseline, but individual choices (a library, a storage format, a trade-off) will be made during sprints and need a lightweight, durable record so future changes understand why the code looks the way it does.

## Decision

We record significant architecture decisions as Architecture Decision Records (ADRs) in `docs/adr/`:

- Numbered sequentially (`0001`, `0002`, …), never renumbered.
- One decision per file, using [`template.md`](template.md).
- Status lifecycle: Proposed → Accepted → Superseded by ADR-N.
- The baseline design lives in [`architecture.md`](../../architecture.md); an Accepted ADR either documents a decision inside that baseline or amends it.

## Consequences

- Decisions are reviewable and reversible with context intact.
- Docs and code can drift from ADRs unless each sprint checks whether its changes invalidate a recorded decision — this check is part of the sprint loop in [`AGENTS.md`](../../AGENTS.md).
