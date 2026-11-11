"""Historical candle import: windowed fetching, validation, dedup, gaps.

Roadmap Sprint 4. The importer pages the requested range into windows of
at most ``MAX_CANDLES_PER_REQUEST`` buckets, stores each window through
the deduplicating repository, quarantines invalid candles (never stored),
and reports the missing intervals left after storage. A progress callback
keeps future UI wiring simple.

``fetch_page`` is injected so authenticated credentials, the public
endpoint family, and test fixtures all plug into the same pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import ceil
from typing import Protocol

from trendbot.database.repositories import CandleRepository
from trendbot.database.session import Database
from trendbot.exchange.coinbase_rest import MAX_CANDLES_PER_REQUEST
from trendbot.market_data.aggregate import aggregate_candles
from trendbot.market_data.candles import Candle
from trendbot.market_data.gaps import find_missing_ranges
from trendbot.market_data.granularity import (
    bucket_floor,
    granularity_for_timeframe,
    granularity_seconds,
)


class CandlePageLike(Protocol):
    """Structural type for the injected fetch result (duck-typed CandlePage)."""

    @property
    def candles(self) -> list[Candle]: ...

    @property
    def rejected_reasons(self) -> list[str]: ...

    @property
    def rejected_count(self) -> int: ...


@dataclass(frozen=True)
class ImportProgress:
    windows_total: int
    windows_done: int
    candles_new: int
    candles_rejected: int


@dataclass(frozen=True)
class ImportSummary:
    product_id: str
    timeframe: str
    granularity: str
    requested_buckets: int
    imported: int
    duplicates: int
    rejected: int
    missing_ranges: list[tuple[datetime, datetime]] = field(default_factory=list)


class CandleImporter:
    """Imports validated historical candles into the durable store."""

    def __init__(self, database: Database, repository: CandleRepository | None = None) -> None:
        self._db = database
        self._repo = repository or CandleRepository(database)

    def import_history(
        self,
        *,
        fetch_page: Callable[[datetime, datetime], CandlePageLike],
        product_id: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        from_timeframe: str | None = None,
        progress: Callable[[ImportProgress], None] | None = None,
    ) -> ImportSummary:
        """Import ``[start, end)`` for one product/timeframe (UTC datetimes).

        When ``timeframe`` is natively supported (all five roadmap
        timeframes are), windows are fetched at that granularity directly.
        With ``from_timeframe`` set — or for a non-native timeframe —
        candles are fetched at the verified lower interval and aggregated
        (architecture.md §7 fallback).
        """
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Import ranges require timezone-aware UTC datetimes.")
        if end <= start:
            raise ValueError("The import range end must be after its start.")

        granularity = granularity_for_timeframe(timeframe)
        seconds = granularity_seconds(granularity)
        aggregate_from: str | None = (
            granularity_for_timeframe(from_timeframe) if from_timeframe is not None else None
        )

        aligned_start = bucket_floor(start, seconds)
        requested_buckets = int(ceil((end - aligned_start).total_seconds() / seconds))

        imported = 0
        rejected = 0
        fetched_valid = 0

        if aggregate_from is not None:
            base_seconds = granularity_seconds(aggregate_from)
            windows = _windows(start, end, base_seconds)
            base_candles: list[Candle] = []
            for index, (w_start, w_end) in enumerate(windows, start=1):
                page = fetch_page(w_start, w_end)
                base_candles.extend(page.candles)
                rejected += page.rejected_count
                if progress is not None:
                    progress(ImportProgress(len(windows), index, imported, rejected))
            target_candles = aggregate_candles(
                base_candles,
                from_granularity=aggregate_from,
                to_granularity=granularity,
            )
            fetched_valid = len(target_candles)
            imported += self._repo.upsert_many(target_candles, source="local_aggregated")
        else:
            windows = _windows(aligned_start, end, seconds)
            for index, (w_start, w_end) in enumerate(windows, start=1):
                page = fetch_page(w_start, w_end)
                fetched_valid += len(page.candles)
                rejected += page.rejected_count
                imported += self._repo.upsert_many(page.candles)
                if progress is not None:
                    progress(ImportProgress(len(windows), index, imported, rejected))

        stored_starts = [
            candle.start_time
            for candle in self._repo.get_range(product_id, granularity, aligned_start, end)
        ]
        missing = find_missing_ranges(stored_starts, aligned_start, end, seconds)
        return ImportSummary(
            product_id=product_id,
            timeframe=timeframe,
            granularity=granularity,
            requested_buckets=requested_buckets,
            imported=imported,
            duplicates=max(fetched_valid - imported, 0),
            rejected=rejected,
            missing_ranges=missing,
        )


def _windows(start: datetime, end: datetime, seconds: int) -> list[tuple[datetime, datetime]]:
    """Split ``[start, end)`` into fetch windows of ≤350 buckets each."""
    window = timedelta(seconds=MAX_CANDLES_PER_REQUEST * seconds)
    windows: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        windows.append((current, min(current + window, end)))
        current += window
    return windows
