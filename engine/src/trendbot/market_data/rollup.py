"""Derived higher-timeframe candles from the live 5-minute feed.

The live feed stores FIVE_MINUTE candles only (architecture.md §7). Strategy
configs saved with a larger timeframe (e.g. 1h) need those buckets to exist
before anything can evaluate them. This service derives ONE_HOUR candles from
complete 5-minute candles via the shared, validated aggregation helper.

Only fully complete hours are stored: ``upsert_many`` conflicts on the candle
key and does nothing, so an incomplete hour stored today would block its
complete replacement tomorrow. Late-arriving 5-minute candles (backfill) are
picked up automatically on a later cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trendbot.database.repositories import CandleRepository
from trendbot.database.session import Database
from trendbot.market_data.aggregate import aggregate_candles
from trendbot.market_data.granularity import bucket_floor, granularity_seconds

SOURCE_GRANULARITY = "FIVE_MINUTE"
TARGET_GRANULARITY = "ONE_HOUR"
MAX_CATCHUP_HOURS = 48
SUBCANDLES_PER_HOUR = 12


class HourlyRollupService:
    """Derive and store ONE_HOUR candles from stored FIVE_MINUTE candles."""

    def __init__(self, database: Database) -> None:
        self._candles = CandleRepository(database)

    def rollup(self, product_id: str, *, now: datetime | None = None) -> int:
        """Store every newly complete hour. Returns the number stored.

        Hours are considered in ascending order starting after the latest
        stored 1h candle, bounded by ``MAX_CATCHUP_HOURS`` per call so a
        long outage catches up over a few cycles instead of one burst.
        """
        moment = now or datetime.now(UTC)
        source_seconds = granularity_seconds(SOURCE_GRANULARITY)
        hour_seconds = granularity_seconds(TARGET_GRANULARITY)
        if hour_seconds % source_seconds != 0:
            return 0

        latest_stored = self._candles.latest_complete_start(product_id, TARGET_GRANULARITY)
        latest_source = self._candles.latest_complete_start(product_id, SOURCE_GRANULARITY)
        if latest_source is None:
            return 0

        # A hour bucket is derivable when every one of its 5-minute candles
        # is complete — the newest possible bucket ends at the floor of the
        # newest complete source candle.
        first_candidate: datetime
        if latest_stored is None:
            oldest_source = self._candles.oldest_start(product_id, SOURCE_GRANULARITY)
            if oldest_source is None:
                return 0
            first_candidate = bucket_floor(oldest_source, hour_seconds)
        else:
            first_candidate = latest_stored + timedelta(seconds=hour_seconds)
        # The newest derivable hour is the bucket containing the newest
        # complete 5-minute candle — but only when that bucket already has
        # its twelfth (55-minute) sub-candle; otherwise the previous hour
        # is the newest one we can fully cover.
        newest_bucket = bucket_floor(latest_source, hour_seconds)
        hour_fully_covered = latest_source == newest_bucket + timedelta(
            seconds=hour_seconds - source_seconds
        )
        last_candidate = (
            newest_bucket if hour_fully_covered else newest_bucket - timedelta(seconds=hour_seconds)
        )

        stored = 0
        bucket = first_candidate
        while bucket <= last_candidate and stored < MAX_CATCHUP_HOURS:
            window_end = bucket + timedelta(seconds=hour_seconds)
            sub_candles = self._candles.get_range(
                product_id, SOURCE_GRANULARITY, bucket, window_end
            )
            complete_sub = [candle for candle in sub_candles if candle.is_complete]
            if len(complete_sub) == SUBCANDLES_PER_HOUR:
                derived = aggregate_candles(
                    complete_sub,
                    from_granularity=SOURCE_GRANULARITY,
                    to_granularity=TARGET_GRANULARITY,
                )
                complete = [
                    candle
                    for candle in derived
                    if candle.is_complete and candle.start_time < moment
                ]
                if complete:
                    stored += self._candles.upsert_many(complete, source="derived_5m")
            bucket = window_end
        return stored
