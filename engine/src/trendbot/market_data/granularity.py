"""Granularity model: verified Coinbase labels, roadmap timeframes, UTC buckets.

Facts pinned by Sprint 0 verification (``docs/coinbase-verification-checklist.md``,
item 4): the REST candles endpoint accepts the granularity labels below, all
five roadmap timeframes (1m/5m/15m/1h/4h) are natively supported —
``FOUR_HOUR`` exists — so aggregation is only needed as the documented
fallback for non-native combinations.
"""

from __future__ import annotations

from datetime import UTC, datetime

GRANULARITY_SECONDS: dict[str, int] = {
    "ONE_MINUTE": 60,
    "FIVE_MINUTE": 300,
    "FIFTEEN_MINUTE": 900,
    "THIRTY_MINUTE": 1800,
    "ONE_HOUR": 3600,
    "TWO_HOUR": 7200,
    "FOUR_HOUR": 14400,
    "SIX_HOUR": 21600,
    "ONE_DAY": 86400,
}

# The roadmap timeframes (architecture.md §2/§7) mapped to verified labels.
TIMEFRAME_GRANULARITY: dict[str, str] = {
    "1m": "ONE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "1h": "ONE_HOUR",
    "4h": "FOUR_HOUR",
}

# Verified lower interval used when a target timeframe needs aggregation.
AGGREGATION_FALLBACK_TIMEFRAME = "1m"


def granularity_seconds(label: str) -> int:
    """Return the bucket size in seconds for a verified granularity label."""
    try:
        return GRANULARITY_SECONDS[label]
    except KeyError:
        raise KeyError(
            f"Granularity {label!r} is not supported. "
            f"Supported: {', '.join(sorted(GRANULARITY_SECONDS))}."
        ) from None


def granularity_for_timeframe(timeframe: str) -> str:
    """Map a roadmap timeframe (e.g. '1h') to its verified granularity label."""
    try:
        return TIMEFRAME_GRANULARITY[timeframe]
    except KeyError:
        raise KeyError(
            f"Timeframe {timeframe!r} is not supported. "
            f"Supported: {', '.join(TIMEFRAME_GRANULARITY)}."
        ) from None


def bucket_floor(moment: datetime, seconds: int) -> datetime:
    """Floor a UTC moment to the start of its bucket (UTC-aligned boundaries)."""
    if moment.tzinfo is None:
        raise ValueError("Bucket alignment requires timezone-aware UTC datetimes.")
    timestamp = int(moment.astimezone(UTC).timestamp())
    aligned = timestamp - (timestamp % seconds)
    return datetime.fromtimestamp(aligned, tz=UTC)
