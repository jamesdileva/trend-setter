# Sprint 13 — Operational readiness (easy wins)

- **Roadmap sprint:** Sprint 13 (partial — easy wins before the soak test) in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** In progress
- **Date:** 2026-11-13

## Goal

Reliability items that can be implemented and tested without the 72-hour soak: rotating log files, backup on shutdown, chart data retry, and engine lifecycle events.

## Scope

Engine (`engine/`):

- **Log rotation** — rotating file handler writing to the app data directory (daily rotation, 7-day retention), so a 24/7 engine doesn't grow unbounded stdout logs
- **Backup on shutdown** — the engine creates a database backup before clean shutdown (uvicorn shutdown signal)
- **Engine lifecycle events** — record `engine_started` and `engine_stopped` in `engine_events` on startup/shutdown

Desktop:

- **CandleChart retry** — the chart polls for data instead of showing a permanent error when the engine just started

Out of scope: the 72-hour soak test (operator runs it after Sprint 14), disk-full simulation, memory profiling, usability testing.

## Acceptance criteria

- [ ] Engine logs rotate daily with bounded retention
- [ ] Database backup is created on clean shutdown
- [ ] CandleChart retries for data instead of showing a permanent error
- [ ] Engine lifecycle events recorded (started/stopped)
- [ ] All existing tests still pass

## Verification

(to be filled before closing)

## Deviations & follow-ups

-
