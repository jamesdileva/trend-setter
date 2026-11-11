"""Deterministic candle aggregation (architecture.md §7; implementation.md §7).

Used when a requested timeframe has no native exchange granularity
(all five roadmap timeframes are native today — this is the documented
fallback), and validated against hand-calculated fixtures.

Rules: open is the first open, high is the maximum high, low is the
minimum low, close is the last close, volume is summed. Buckets align to
UTC boundaries. A resulting candle is complete only when the group covers
every expected sub-bucket.
"""

from __future__ import annotations

from datetime import datetime

from trendbot.market_data.candles import Candle
from trendbot.market_data.granularity import bucket_floor, granularity_seconds


def aggregate_candles(
    candles: list[Candle],
    *,
    from_granularity: str,
    to_granularity: str,
) -> list[Candle]:
    """Aggregate ``from_granularity`` candles into ``to_granularity`` buckets.

    Input candles are sorted by start time; they must all share the source
    granularity. The result is ordered by bucket start, with the source
    marked via the candle's granularity label.
    """
    from_seconds = granularity_seconds(from_granularity)
    to_seconds = granularity_seconds(to_granularity)
    if to_seconds <= from_seconds or to_seconds % from_seconds != 0:
        raise ValueError(
            f"Cannot aggregate from {from_granularity} to {to_granularity}: "
            "the target bucket must be a whole multiple of the source bucket."
        )
    ratio = to_seconds // from_seconds
    if not candles:
        return []

    ordered = sorted(candles, key=lambda candle: candle.start_time)
    for candle in ordered:
        if candle.granularity != from_granularity:
            raise ValueError(
                f"Aggregation input must all be {from_granularity} candles; "
                f"found {candle.granularity!r}."
            )

    groups: dict[datetime, list[Candle]] = {}
    order: list[datetime] = []
    for candle in ordered:
        bucket = bucket_floor(candle.start_time, to_seconds)
        if bucket not in groups:
            groups[bucket] = []
            order.append(bucket)
        groups[bucket].append(candle)

    product_id = ordered[0].product_id
    aggregated: list[Candle] = []
    for bucket in order:
        group = groups[bucket]
        aggregated.append(
            Candle(
                product_id=product_id,
                granularity=to_granularity,
                start_time=bucket,
                open=group[0].open,
                high=max(candle.high for candle in group),
                low=min(candle.low for candle in group),
                close=group[-1].close,
                volume=sum((candle.volume for candle in group), start=group[0].volume * 0),
                is_complete=len(group) == ratio,
            )
        )
    return aggregated
