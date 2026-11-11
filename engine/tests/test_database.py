"""Tests for the durable data layer (roadmap Sprint 2 verification).

Covers: PRAGMA configuration, decimal-string and UTC round-trips,
duplicate candle/fill deduplication, foreign-key enforcement, and the
failed-write -> rollback -> health-event flow.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from trendbot.database import (
    CandleRepository,
    Database,
    DatabaseWriteError,
    EngineEventRepository,
    FillRepository,
    SettingsRepository,
    upgrade_to_head,
)
from trendbot.database.models import CandleRecord, EngineEvent, ExchangeOrder, FillRecord
from trendbot.exchange.types import Fill, OrderSide
from trendbot.market_data.candles import Candle


@pytest.fixture()
def migrated_db(tmp_path):
    database = Database(tmp_path / "trendbot.db")
    upgrade_to_head(database)
    return database


def sample_candle(
    product_id: str = "BTC-USD",
    start_time: datetime | None = None,
    *,
    open_: Decimal = Decimal("65000.13"),
) -> Candle:
    start_time = start_time or datetime(2026, 1, 1, 13, tzinfo=UTC)
    return Candle(
        product_id=product_id,
        granularity="ONE_HOUR",
        start_time=start_time,
        open=open_,
        high=Decimal("65001.99"),
        low=Decimal("64998.01"),
        close=Decimal("65000.50"),
        volume=Decimal("12.3456789"),
    )


def sample_fill(exchange_order_id: str = "ord-1", trade_id: str = "t-1") -> Fill:
    return Fill(
        exchange_order_id=exchange_order_id,
        trade_id=trade_id,
        product_id="BTC-USD",
        side=OrderSide.BUY,
        price=Decimal("65000.00"),
        size=Decimal("0.001"),
        commission=Decimal("0.05"),
        trade_time=datetime(2026, 1, 1, 13, 5, tzinfo=UTC),
    )


class TestSqliteConfiguration:
    def test_pragmas_are_applied_to_connections(self, tmp_path):
        database = Database(tmp_path / "trendbot.db")
        assert database.execute_scalar("PRAGMA foreign_keys") == 1
        assert database.execute_scalar("PRAGMA busy_timeout") == 5000
        assert database.execute_scalar("PRAGMA journal_mode") == "wal"


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """Flatten a chained exception into a list (direct __cause__ links)."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None:
        chain.append(current)
        current = current.__cause__
    return chain


class TestPersistenceConventions:
    def test_financial_values_round_trip_without_float_corruption(self, migrated_db):
        repository = CandleRepository(migrated_db)
        repository.upsert_many([sample_candle()])
        stored = repository.get_range(
            "BTC-USD",
            "ONE_HOUR",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert stored[0].open == Decimal("65000.13")
        assert stored[0].volume == Decimal("12.3456789")
        assert stored[0].start_time.utcoffset() == timedelta(0)

    def test_money_is_stored_as_decimal_strings_not_floats(self, migrated_db):
        CandleRepository(migrated_db).upsert_many([sample_candle()])
        raw = migrated_db.execute_scalar("SELECT open FROM candles LIMIT 1")
        assert raw == "65000.13"

    def test_binary_floats_are_rejected_at_the_boundary(self, migrated_db):
        with pytest.raises(DatabaseWriteError) as excinfo:
            with migrated_db.session() as session:
                session.add(
                    CandleRecord(
                        product_id="BTC-USD",
                        granularity="ONE_HOUR",
                        start_time=datetime(2026, 1, 1, tzinfo=UTC),
                        open=65000.13,  # type: ignore[arg-type] - deliberate violation
                        high=Decimal("65001"),
                        low=Decimal("64998"),
                        close=Decimal("65000"),
                        volume=Decimal("1"),
                    )
                )
                session.flush()
        assert any(isinstance(item, TypeError) for item in _exception_chain(excinfo.value))

    def test_naive_timestamps_are_rejected(self, migrated_db):
        with pytest.raises(DatabaseWriteError) as excinfo:
            with migrated_db.session() as session:
                session.add(
                    CandleRecord(
                        product_id="BTC-USD",
                        granularity="ONE_HOUR",
                        start_time=datetime(2026, 1, 1),  # naive — deliberate violation
                        open=Decimal("1"),
                        high=Decimal("2"),
                        low=Decimal("0.5"),
                        close=Decimal("1.5"),
                        volume=Decimal("1"),
                    )
                )
                session.flush()
        assert any(isinstance(item, ValueError) for item in _exception_chain(excinfo.value))


class TestDeduplication:
    def test_duplicate_candles_are_safely_deduplicated(self, migrated_db):
        repository = CandleRepository(migrated_db)
        first = sample_candle()
        second = sample_candle(product_id="ETH-USD")
        assert repository.upsert_many([first, first, second]) == 2
        assert repository.count() == 2
        assert repository.upsert_many([first, second]) == 0
        assert repository.count() == 2

    def test_duplicate_fills_never_double_count(self, migrated_db):
        with migrated_db.session() as session:
            session.add(
                ExchangeOrder(
                    exchange_order_id="ord-1",
                    client_order_id="c-1",
                    product_id="BTC-USD",
                    side="buy",
                    status="FILLED",
                )
            )
        repository = FillRepository(migrated_db)
        assert repository.record_fill(sample_fill()) is True
        assert repository.record_fill(sample_fill()) is False
        with migrated_db.session() as session:
            assert int(session.query(FillRecord).count()) == 1

    def test_engine_events_are_idempotent_with_a_dedupe_key(self, migrated_db):
        repository = EngineEventRepository(migrated_db)
        first_id = repository.append(
            event_type="market_data",
            component="websocket",
            message="Reconnected after a gap.",
            dedupe_key="reconnect-2026-01-01T13:00Z",
        )
        second_id = repository.append(
            event_type="market_data",
            component="websocket",
            message="Reconnected after a gap.",
            dedupe_key="reconnect-2026-01-01T13:00Z",
        )
        assert first_id == second_id
        fresh_id = repository.append(
            event_type="market_data", component="websocket", message="Fresh event."
        )
        assert fresh_id != first_id


class TestForeignKeyEnforcement:
    def test_orphan_fill_is_rejected_by_foreign_keys(self, migrated_db):
        with pytest.raises(DatabaseWriteError) as excinfo:
            with migrated_db.session() as session:
                session.add(
                    FillRecord(
                        entry_id="orphan-1",
                        trade_id="t-9",
                        exchange_order_id="missing-order",
                        product_id="BTC-USD",
                        side="buy",
                        price=Decimal("1"),
                        size=Decimal("1"),
                        commission=Decimal("0"),
                        trade_time=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                )
                session.flush()
        assert isinstance(excinfo.value.__cause__, IntegrityError)


class TestFailureHandling:
    def test_failed_write_rolls_back_and_records_a_health_event(self, migrated_db):
        with pytest.raises(DatabaseWriteError):
            with migrated_db.session() as session:
                session.add(CandleRecord(**_valid_candle_fields()))
                session.add(FillRecord(**_orphan_fill_fields()))
                session.flush()

        # The whole transaction rolled back: the valid candle is not kept.
        assert CandleRepository(migrated_db).count() == 0

        assert migrated_db.write_failure("test", "simulated write failure") is True
        with migrated_db.session() as session:
            failures = (
                session.query(EngineEvent)
                .filter(EngineEvent.event_type == "database_write_failed")
                .count()
            )
        assert failures == 1


def _valid_candle_fields() -> dict[str, object]:
    return {
        "product_id": "BTC-USD",
        "granularity": "ONE_HOUR",
        "start_time": datetime(2026, 1, 1, 14, tzinfo=UTC),
        "open": Decimal("1"),
        "high": Decimal("2"),
        "low": Decimal("0.5"),
        "close": Decimal("1.5"),
        "volume": Decimal("10"),
    }


def _orphan_fill_fields() -> dict[str, object]:
    return {
        "entry_id": "orphan-1",
        "trade_id": "t-9",
        "exchange_order_id": "missing-order",
        "product_id": "BTC-USD",
        "side": "buy",
        "price": Decimal("1"),
        "size": Decimal("1"),
        "commission": Decimal("0"),
        "trade_time": datetime(2026, 1, 1, tzinfo=UTC),
    }


class TestSettings:
    def test_settings_round_trip_and_upsert(self, migrated_db):
        repository = SettingsRepository(migrated_db)
        assert repository.get("missing", "fallback") == "fallback"
        repository.set("ui.theme", "dark")
        assert repository.get("ui.theme") == "dark"
        repository.set("ui.theme", "light")
        assert repository.get("ui.theme") == "light"
