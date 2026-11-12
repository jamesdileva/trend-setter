# Sprint 11 — Main dashboard and nontechnical-user experience

- **Roadmap sprint:** Sprint 11 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** In progress
- **Date:** 2026-11-12

## Goal

Turn the functional cards into an understandable dashboard: plain-language EMA/RSI explanations (the user's request from the smoke test), a candlestick chart with EMA overlays, organized sections, and clear status throughout. The dashboard is the user's window into the always-running engine — not the engine itself.

## Scope

Desktop (`apps/desktop/`), per architecture.md §16 and roadmap Sprint 11 tasks:

- Plain-language strategy explanations: each parameter (Fast/Slow EMA, RSI period, entry ceiling) gets a plain-language description; the card explains what the strategy does in one sentence (the user's explicit request from the smoke test)
- Candlestick chart with EMA overlays using `lightweight-charts` (TradingView; actively maintained, small bundle): rendered from stored candles, with fast/slow EMA lines overlaid
- Market data card improvement: show the latest BTC-USD price (from the newest candle close) alongside the feed status
- Section headers with plain-language subtitles so each card's purpose is obvious without domain knowledge
- Settings persistence: strategy config saves mid-session (re-reads active config per evaluation)

Out of scope: multi-chart layouts, dark/light theme switching, setup walkthrough tour, diagnostics export button, keyboard navigation audit (all later polish sprints).

## Acceptance criteria (roadmap Sprint 11 verification)

- [ ] Strategy parameters have plain-language descriptions
- [ ] Candlestick chart renders stored candles with EMA overlays
- [ ] Every displayed value has a defined source and freshness timestamp
- [ ] Nontechnical tester can understand current state without domain knowledge

## Verification

(to be filled before closing)

## Deviations & follow-ups

-
