"""Persistence tests for configs and signals (roadmap Sprint 6 verification)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect as sa_inspect

from trendbot.application.strategy_engine import StrategyEngine
from trendbot.database import CandleRepository, Database, upgrade_to_head
from trendbot.database.models import Signal
from trendbot.market_data.candles import Candle
from trendbot.strategies.config import EmaRsiConfig

START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "strategy.db")
    upgrade_to_head(database)
    return database


def jump_candles(count: int = 51) -> list[Candle]:
    closes = [Decimal(60)] * (count - 2) + [Decimal(55), Decimal(200)]
    return [
        Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + index * timedelta(hours=1),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=Decimal(1),
        )
        for index, close in enumerate(closes)
    ]


class TestConfigVersioning:
    def test_save_creates_increasing_versions_with_one_active(self, db):
        engine = StrategyEngine(db)
        first = engine.set_config(
            product_id="BTC-USD", timeframe="1h", fast_ema_period=20, slow_ema_period=50
        )
        second = engine.set_config(
            product_id="BTC-USD", timeframe="1h", fast_ema_period=10, slow_ema_period=40
        )
        assert first["version"] == 1
        assert second["version"] == 2
        current = engine.current_config()
        assert current is not None
        assert current.fast_ema_period == 10
        assert current.slow_ema_period == 40

    def test_same_content_keeps_one_hash(self, db):
        engine = StrategyEngine(db)
        first = engine.set_config(product_id="BTC-USD", timeframe="1h")
        engine.set_config(product_id="BTC-USD", timeframe="1h")
        assert first["config_hash"] == EmaRsiConfig(
            product_id="BTC-USD", timeframe="1h"
        ).config_hash()

    def test_invalid_config_is_rejected_plain_language(self, db):
        engine = StrategyEngine(db)
        with pytest.raises(Exception) as excinfo:
            engine.set_config(
                product_id="BTC-USD", timeframe="1h", fast_ema_period=50, slow_ema_period=20
            )
        assert "fast EMA period must be less than the slow EMA period" in str(excinfo.value)


class TestSignalPersistence:
    def test_signal_is_recorded_with_config_and_candle_identity(self, db):
        engine = StrategyEngine(db)
        engine.set_config(
            product_id="BTC-USD",
            timeframe="1h",
            rsi_entry_ceiling=97.0,
        )
        CandleRepository(db).upsert_many(jump_candles())
        decision = engine.evaluate()
        assert decision.signal.value == "buy"
        with db.session() as session:
            rows = session.query(Signal).all()  # type: ignore[attr-defined]
        assert len(rows) == 1
        assert rows[0].decision == "buy"
        assert rows[0].reason_code == "bullish_crossover_rsi_ok"
        assert rows[0].config_hash == decision.config_hash
        assert rows[0].candle_start_time == START + timedelta(hours=50)

    def test_repeated_evaluation_of_the_same_candle_does_not_duplicate(self, db):
        engine = StrategyEngine(db)
        engine.set_config(product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0)
        CandleRepository(db).upsert_many(jump_candles())
        first = engine.evaluate()
        second = engine.evaluate()
        assert first == second
        with db.session() as session:
            assert session.query(Signal).count() == 1  # type: ignore[attr-defined]

    def test_signals_are_reproducible_from_stored_candles_and_config(self, db):
        engine = StrategyEngine(db)
        engine.set_config(product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0)
        CandleRepository(db).upsert_many(jump_candles())
        first = engine.evaluate()

        # A fresh engine over the same stored state reaches the same decision.
        fresh = StrategyEngine(db)
        again = fresh.evaluate()
        assert again == first
        assert again.config_hash == first.config_hash


class TestMigration0002:
    def test_signals_table_carries_the_unique_constraint(self, db):
        inspector = sa_inspect(db.engine)
        uniques = {
            constraint["name"]
            for table in inspector.get_table_names()
            if table == "signals"
            for constraint in inspector.get_unique_constraints(table)
        }
        assert "uq_signal_per_candle" in uniques
