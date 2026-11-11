# Sprint 00 — Coinbase integration verification (Sprint 0 completion)

- **Roadmap sprint:** Sprint 0 in [`../../sprint-roadmap.md`](../../sprint-roadmap.md)
- **Status:** In progress
- **Date:** 2026-11-11

## Goal

Verify every assumed Coinbase Advanced Trade capability against current official documentation and record the evidence, so that no unsupported API behavior is treated as fact before implementation.

## Scope

- Research the 8 items in [`../coinbase-verification-checklist.md`](../coinbase-verification-checklist.md) from official Coinbase Developer Platform documentation (`docs.cdp.coinbase.com`).
- Fill each checklist row: official reference, verified date, test-plan note.
- Add a findings summary recording the exact facts the adapter and tests must encode (granularities, order type enums, `client_order_id` rules, rate limits, protective-order support).
- Update [`../risk-register.md`](../risk-register.md) if verification surfaces new risks.

Out of scope: implementing the Coinbase adapter (Sprint 4+), any live trading, dependency or application code changes.

## Acceptance criteria

- [x] All 8 checklist rows have an official doc reference and a verified date
- [x] Unverifiable or unsupported behaviors are explicitly flagged with a fallback plan
- [x] Findings recorded where the adapter and its tests must match documented behavior

## Verification

Method: current official Coinbase Developer Platform docs (`docs.cdp.coinbase.com`) fetched live on 2026-11-11 (guides under `/coinbase-app/...`, API reference under `/api-reference/advanced-trade-api/...`, Mintlify `.md` extraction). Every fact in [`../coinbase-verification-checklist.md`](../coinbase-verification-checklist.md) carries its supporting URL.

Headline results:

- All five roadmap timeframes (1m/5m/15m/1h/4h) are **natively supported** by the candles endpoint (`FOUR_HOUR` exists — 1h→4h aggregation no longer required for the baseline, kept as documented fallback).
- `client_order_id` has **exchange-side duplicate protection** (reuse returns the existing order, `DUPLICATE_CLIENT_ORDER_ID`) — directly de-risks duplicate-order architecture (R-02).
- A **public unauthenticated** market-data REST family exists (`/market/...`), so paper/backtest mode can run without any API key.
- ES256/ECDSA keys are mandatory (Ed25519 unsupported for Advanced Trade); JWTs expire after 120 s and are per-request (REST) / per-message (WS).
- WS channels close after 60–90 s of inactivity — the `heartbeats` channel is mandatory for liveness (R-03).
- **No native trailing stop** in Advanced Trade spot `place_order`; bracket legs exist via `trigger_bracket_gtc/gtd` + `attached_order_configuration`.
- REST rate limits: no Advanced-Trade-specific numeric REST limit table remains in current docs; closest official figure is the Coinbase-App default of 10,000 req/hour (scope caveat flagged for live verification). WS: 8 connections and 8 unauthenticated messages per second per IP; disconnect if no subscribe within 5 seconds.
- Product metadata field names changed (`base_min_size`/`quote_min_size` replace `min_product_size`/`min_market_funds`) — adapter must use current names.
- Fills **omit `client_order_id`** — reconciliation maps fills to intents via exchange `order_id`.

## Deviations & follow-ups

- Research was started with four parallel subagents; platform concurrency limits cut three of them off, so the remaining verification was completed with direct page fetches (same sources, same evidence standard).
- 7 wire-level details that official docs do not fully settle are listed under "Flagged for adapter-integration verification" in the checklist (granularity wire format, WS candles granularity flexibility, JWT `aud`/`iss` exact values, rate-limit header names, authenticated WS limits, candle window bounds). They are assigned to Sprint 4/5/10 integration tests, not hardcoded.
- Follow-up for Sprint 3 (connection wizard): the CDP key-creation flow defaults to Ed25519 — the wizard must explicitly instruct selecting **ECDSA** when creating the key.
