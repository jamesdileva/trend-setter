"""Stale-data entry gate (roadmap Sprint 5 task 9; architecture.md §7).

"Block new entries when required market data is stale or incomplete" —
this gate is the check every entry intent must pass (wired into execution
in Sprint 8). Decisions carry plain-language reasons shown in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from trendbot.database.repositories import CandleRepository
from trendbot.market_data.granularity import granularity_for_timeframe

DEFAULT_MAX_CANDLE_AGE_SECONDS = 300
DEFAULT_MAX_FEED_SILENCE_SECONDS = 30.0


@dataclass(frozen=True)
class GateDecision:
    """The outcome of a freshness check for one product/timeframe."""

    allowed: bool
    reason_code: str | None  # None when allowed
    message: str


class MarketDataGate:
    """Decides whether market data is fresh enough to allow new entries."""

    def __init__(
        self,
        repository: CandleRepository,
        *,
        max_candle_age_seconds: int = DEFAULT_MAX_CANDLE_AGE_SECONDS,
        max_feed_silence_seconds: float = DEFAULT_MAX_FEED_SILENCE_SECONDS,
    ) -> None:
        self._repo = repository
        self._max_candle_age = max_candle_age_seconds
        self._max_silence = max_feed_silence_seconds

    def check(
        self,
        product_id: str,
        timeframe: str,
        *,
        now: datetime | None = None,
        feed_state: str = "connected",
        feed_last_message_age: float | None = None,
    ) -> GateDecision:
        """Evaluate freshness; never raises — blocking decisions explain why."""
        moment = now or datetime.now(UTC)
        if feed_state != "connected":
            return GateDecision(
                allowed=False,
                reason_code="feed_disconnected",
                message="Live market data is not connected. New entries are paused.",
            )
        if feed_last_message_age is not None and feed_last_message_age > self._max_silence:
            return GateDecision(
                allowed=False,
                reason_code="feed_stale",
                message="Market data is delayed. New entries are paused.",
            )
        try:
            granularity = granularity_for_timeframe(timeframe)
        except KeyError as exc:
            return GateDecision(allowed=False, reason_code="unknown_timeframe", message=str(exc))
        latest = self._repo.latest_complete_start(product_id, granularity)
        if latest is None:
            return GateDecision(
                allowed=False,
                reason_code="no_data",
                message=(
                    f"No completed candles for {product_id} at {timeframe} yet. "
                    "Run an import or wait for the live feed."
                ),
            )
        age = (moment - latest).total_seconds()
        if age > self._max_candle_age:
            return GateDecision(
                allowed=False,
                reason_code="stale_candle",
                message=(
                    f"The newest completed candle is {age:.0f}s old "
                    f"(limit {self._max_candle_age}s). New entries are paused."
                ),
            )
        return GateDecision(allowed=True, reason_code=None, message="Market data is fresh.")
