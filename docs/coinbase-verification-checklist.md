# Coinbase Integration Verification Checklist

**Purpose:** Sprint 0 requires verifying every assumed Coinbase capability against current official documentation before implementation. No unsupported API behavior may be treated as fact — see Sprint 0 in [`sprint-roadmap.md`](../sprint-roadmap.md) and §21 of [`architecture.md`](../architecture.md).

For each item: record the official doc you verified against, the verification date, and where a test plan covers the behavior.

| # | Capability to verify | Official reference | Verified on | Test plan |
|---|---|---|---|---|
| 1 | CDP API key creation and authentication requirements | _pending_ | | |
| 2 | Required key permissions for account reads, market data, trading | _pending_ | | |
| 3 | Current REST and WebSocket endpoints/channels | _pending_ | | |
| 4 | Supported candle granularities and historical candle limits | _pending_ | | |
| 5 | Product increments, minimum sizes, order types | _pending_ | | |
| 6 | Client order ID semantics and duplicate handling | _pending_ | | |
| 7 | Rate limits and retry guidance | _pending_ | | |
| 8 | Protective and trailing order type availability/behavior | _pending_ | | |

**Exit rule:** no sprint that touches the live Coinbase adapter may start while any row above is unverified, unless the sprint roadmap explicitly records the deferral.
