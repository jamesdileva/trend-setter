"""Hourly rollup from the live 5-minute feed (Sprint 15)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.database import CandleRepository, Database, upgrade_to_head
from trendbot.market_data.candles import Candle
from trendbot.market_data.rollup import HourlyRollupService


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "rollup.db")
    upgrade_to_head(database)
    return database


def five_minute_candle(
    start: datetime,
    close_base: int = 100,
    *,
    complete: bool = True,
    product_id: str = "BTC-USD",
) -> Candle:
    """Deterministic 5m candle; the 12 candles of an hour step open 100..111."""
    step = start.minute // 5
    open_price = close_base + step
    return Candle(
        product_id=product_id,
        granularity="FIVE_MINUTE",
        start_time=start,
        open=Decimal(open_price),
        high=Decimal(open_price + 2),
        low=Decimal(open_price - 2),
        close=Decimal(open_price + 1),
        volume=Decimal("1.5"),
        is_complete=complete,
    )


def hour_candles(hour_start: datetime, *, complete: bool = True) -> list[Candle]:
    return [
        five_minute_candle(hour_start + timedelta(minutes=5 * i), complete=complete)
        for i in range(12)
    ]


class TestHourlyRollup:
    def test_derives_complete_hour(self, db):
        repo = CandleRepository(db)
        hour = datetime(2026, 11, 16, 14, tzinfo=UTC)
        repo.upsert_many(hour_candles(hour), source="exchange")

        service = HourlyRollupService(db)
        stored = service.rollup("BTC-USD")

        assert stored == 1
        derived = repo.get_range(
            "BTC-USD", "ONE_HOUR", hour, hour + timedelta(hours=1)
        )
        assert len(derived) == 1
        candle = derived[0]
        assert candle.is_complete is True
        # open = first sub-candle open, close = last sub-candle close,
        # high/low cover the whole group, volume summed.
        assert candle.open == Decimal(100)
        assert candle.close == Decimal(112)
        assert candle.high == Decimal(113)
        assert candle.low == Decimal(98)
        assert candle.volume == Decimal("18.0")

    def test_skips_hour_with_missing_candle_and_stores_it_after_backfill(self, db):
        repo = CandleRepository(db)
        hour = datetime(2026, 11, 16, 14, tzinfo=UTC)
        # A feed gap: the 55-minute candle is missing entirely (the feed
        # stores only complete candles; backfill fills the hole later).
        repo.upsert_many(hour_candles(hour)[:-1], source="exchange")

        service = HourlyRollupService(db)
        assert service.rollup("BTC-USD") == 0
        assert repo.get_range("BTC-USD", "ONE_HOUR", hour, hour + timedelta(hours=1)) == []

        # Backfill inserts the missing candle; the next cycle stores the hour.
        repo.upsert_many(
            [five_minute_candle(hour + timedelta(minutes=55))], source="exchange"
        )
        assert service.rollup("BTC-USD") == 1

    def test_does_not_restore_existing_hours(self, db):
        repo = CandleRepository(db)
        hour = datetime(2026, 11, 16, 14, tzinfo=UTC)
        repo.upsert_many(hour_candles(hour), source="exchange")
        service = HourlyRollupService(db)

        assert service.rollup("BTC-USD") == 1
        assert service.rollup("BTC-USD") == 0  # already stored

    def test_catches_up_multiple_hours_after_gap(self, db):
        repo = CandleRepository(db)
        base = datetime(2026, 11, 16, 12, tzinfo=UTC)
        candles: list[Candle] = []
        for offset in range(3):
            candles.extend(hour_candles(base + timedelta(hours=offset)))
        repo.upsert_many(candles, source="exchange")

        service = HourlyRollupService(db)
        assert service.rollup("BTC-USD") == 3
        assert service.rollup("BTC-USD") == 0

    def test_no_source_data_is_a_noop(self, db):
        service = HourlyRollupService(db)
        assert service.rollup("BTC-USD") == 0

    def test_products_do_not_mix(self, db):
        repo = CandleRepository(db)
        hour = datetime(2026, 11, 16, 14, tzinfo=UTC)
        repo.upsert_many(
            hour_candles(hour), source="exchange"
        )
        eth = HourlyRollupService(db)
        assert eth.rollup("ETH-USD") == 0
