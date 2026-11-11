"""Offline tests for the REST gap backfiller (roadmap Sprint 5 verification)."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.database import CandleRepository, Database, upgrade_to_head
from trendbot.exchange.coinbase_rest import CandlePage
from trendbot.market_data.backfill import GapBackfiller
from trendbot.market_data.candles import Candle

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "backfill.db")
    upgrade_to_head(database)
    return database


def hourly_fetch(w_start: datetime, w_end: datetime) -> CandlePage:
    candles = []
    current = w_start
    while current < w_end:
        price = Decimal(100 + (int(current.timestamp()) // 3600) % 7)
        candles.append(
            Candle(
                product_id="BTC-USD",
                granularity="ONE_HOUR",
                start_time=current,
                open=price,
                high=price + 2,
                low=price - 2,
                close=price + 1,
                volume=Decimal("1"),
                is_complete=True,
            )
        )
        current += timedelta(hours=1)
    return CandlePage(candles=candles, rejected_reasons=[])


class TestBackfill:
    def test_backfill_fills_the_missed_range(self, db):
        fetch_builder = lambda product_id, timeframe: hourly_fetch  # noqa: E731
        backfiller = GapBackfiller(db, fetch_builder)
        summary = asyncio.run(
            backfiller.backfill("BTC-USD", "1h", START, START + timedelta(hours=5))
        )
        assert summary is not None
        assert summary.imported == 5
        assert CandleRepository(db).count() == 5

    def test_backfill_is_idempotent(self, db):
        fetch_builder = lambda product_id, timeframe: hourly_fetch  # noqa: E731
        backfiller = GapBackfiller(db, fetch_builder)
        first = asyncio.run(
            backfiller.backfill("BTC-USD", "1h", START, START + timedelta(hours=5))
        )
        second = asyncio.run(
            backfiller.backfill("BTC-USD", "1h", START, START + timedelta(hours=5))
        )
        assert first is not None and first.imported == 5
        assert second is not None and second.imported == 0
        assert CandleRepository(db).count() == 5

    def test_empty_range_is_skipped(self, db):
        backfiller = GapBackfiller(db, lambda product_id, timeframe: hourly_fetch)
        assert asyncio.run(backfiller.backfill("BTC-USD", "1h", START, START)) is None
