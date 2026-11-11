"""Missing-interval detection for candle ranges (roadmap Sprint 4 task 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def expected_starts(start: datetime, end: datetime, seconds: int) -> list[datetime]:
    """Every bucket start in ``[start, end)`` at ``seconds`` spacing (UTC)."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Gap detection requires timezone-aware UTC datetimes.")
    starts: list[datetime] = []
    current = start.astimezone(UTC)
    last = end.astimezone(UTC)
    while current < last:
        starts.append(current)
        current += timedelta(seconds=seconds)
    return starts


def find_missing_ranges(
    present: list[datetime] | set[datetime],
    start: datetime,
    end: datetime,
    seconds: int,
) -> list[tuple[datetime, datetime]]:
    """Collapse missing buckets in ``[start, end)`` into ``[start, end)`` ranges.

    Returns an empty list when the range is fully covered.
    """
    present_starts = set(present)
    missing = [
        bucket
        for bucket in expected_starts(start, end, seconds)
        if bucket not in present_starts
    ]

    ranges: list[tuple[datetime, datetime]] = []
    step = timedelta(seconds=seconds)
    run_start: datetime | None = None
    previous: datetime | None = None
    for bucket in missing:
        if run_start is None:
            run_start = bucket
        elif previous is not None and bucket - previous != step:
            ranges.append((run_start, previous + step))
            run_start = bucket
        previous = bucket
    if run_start is not None and previous is not None:
        ranges.append((run_start, previous + step))
    return ranges
