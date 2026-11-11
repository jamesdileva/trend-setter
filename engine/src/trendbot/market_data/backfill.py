"""REST backfill of missed candle windows (roadmap Sprint 5 task 7).

The live feed detects gaps (disconnects, silence, sequence jumps) and
hands ranges to :class:`GapBackfiller`, which runs the Sprint 4 importer
over the gap. Backfill is idempotent: repeated fills deduplicate through
the unique candle key, and a restore never replays old intents — the
importer only ever appends candles.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from trendbot.database.session import Database
from trendbot.market_data.importer import CandleImporter, CandlePageLike, ImportSummary

FetchPage = Callable[[datetime, datetime], CandlePageLike]
FetchBuilder = Callable[[str, str], FetchPage]


class GapBackfiller:
    """Fills detected gaps through the REST importer (off the feed loop)."""

    def __init__(self, database: Database, fetch_builder: FetchBuilder) -> None:
        self._database = database
        self._fetch_builder = fetch_builder

    async def backfill(
        self, product_id: str, timeframe: str, gap_start: datetime, gap_end: datetime
    ) -> ImportSummary | None:
        """Import ``[gap_start, gap_end)``; returns None when the range is empty.

        Runs the blocking importer in a worker thread so the feed loop and
        the API stay responsive. Failures propagate to the caller (the
        feed records them as engine events without dying).
        """
        if gap_end <= gap_start:
            return None
        return await asyncio.to_thread(
            self._import_sync, product_id, timeframe, gap_start, gap_end
        )

    def _import_sync(
        self, product_id: str, timeframe: str, gap_start: datetime, gap_end: datetime
    ) -> ImportSummary:
        fetch_page = self._fetch_builder(product_id, timeframe)
        return CandleImporter(self._database).import_history(
            fetch_page=fetch_page,
            product_id=product_id,
            timeframe=timeframe,
            start=gap_start,
            end=gap_end,
        )
