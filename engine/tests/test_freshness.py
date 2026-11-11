"""Offline tests for the stale-data entry gate (roadmap Sprint 5 verification)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.database import CandleRepository, Database, upgrade_to_head
from trendbot.market_data.candles import Candle
from trendbot.market_data.freshness import MarketDataGate

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "gate.db")
    upgrade_to_head(database)
    return database


def complete_candle(start: datetime) -> Candle:
    return Candle(
        product_id="BTC-USD",
        granularity="ONE_HOUR",
        start_time=start,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("1"),
        is_complete=True,
    )


class TestGate:
    def test_disconnected_feed_blocks_entries(self, db):
        gate = MarketDataGate(CandleRepository(db))
        decision = gate.check("BTC-USD", "1h", feed_state="reconnecting")
        assert decision.allowed is False
        assert decision.reason_code == "feed_disconnected"
        assert "paused" in decision.message

    def test_silent_feed_blocks_entries(self, db):
        gate = MarketDataGate(CandleRepository(db))
        decision = gate.check("BTC-USD", "1h", feed_last_message_age=120.0)
        assert decision.allowed is False
        assert decision.reason_code == "feed_stale"

    def test_no_data_blocks_entries_with_guidance(self, db):
        gate = MarketDataGate(CandleRepository(db))
        decision = gate.check("BTC-USD", "1h", now=NOW)
        assert decision.allowed is False
        assert decision.reason_code == "no_data"
        assert "import" in decision.message

    def test_stale_completed_candle_blocks_entries(self, db):
        repository = CandleRepository(db)
        repository.upsert_many([complete_candle(NOW - timedelta(hours=2))])
        gate = MarketDataGate(CandleRepository(db), max_candle_age_seconds=300)
        decision = gate.check("BTC-USD", "1h", now=NOW)
        assert decision.allowed is False
        assert decision.reason_code == "stale_candle"
        assert "paused" in decision.message

    def test_fresh_completed_candle_allows_entries(self, db):
        repository = CandleRepository(db)
        repository.upsert_many([complete_candle(NOW - timedelta(minutes=1))])
        gate = MarketDataGate(CandleRepository(db), max_candle_age_seconds=300)
        decision = gate.check("BTC-USD", "1h", now=NOW)
        assert decision.allowed is True
        assert decision.reason_code is None

    def test_incomplete_candle_does_not_satisfy_the_gate(self, db):
        repository = CandleRepository(db)
        stale_complete = complete_candle(NOW - timedelta(hours=2))
        fresh_incomplete = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=NOW - timedelta(minutes=1),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("1"),
            is_complete=False,
        )
        repository.upsert_many([stale_complete, fresh_incomplete])
        gate = MarketDataGate(CandleRepository(db), max_candle_age_seconds=300)
        decision = gate.check("BTC-USD", "1h", now=NOW)
        # The gate reads complete candles only — a fresh partial candle
        # must not unblock entries while the last complete one is stale.
        assert decision.allowed is False

    def test_unknown_timeframe_blocks_with_plain_language(self, db):
        gate = MarketDataGate(CandleRepository(db))
        decision = gate.check("BTC-USD", "3h", now=NOW)
        assert decision.allowed is False
        assert decision.reason_code == "unknown_timeframe"
