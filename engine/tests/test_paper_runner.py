"""PaperLoopRunner tests (Sprint 15): the automated trading loop wiring.

The crossover decision fires on the jump candle (index 50 in the fixture),
so candles are added progressively: seed the flat run, then feed the jump
candle (BUY decision), then the next candle (fill at its open).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.application.strategy_engine import StrategyEngine
from trendbot.database import Database, upgrade_to_head
from trendbot.database.repositories import (
    CandleRepository,
    OrderIntentRepository,
    PositionRepository,
)
from trendbot.market_data.candles import Candle
from trendbot.paper.runner import PaperLoopRunner

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
HOURLY = timedelta(hours=1)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "runner.db")
    upgrade_to_head(database)
    return database


class RecordingNotifier:
    def __init__(self) -> None:
        self.fills: list[dict[str, str]] = []
        self.problems: list[tuple[str, str]] = []

    def order_filled(self, **kwargs: str) -> None:
        self.fills.append(kwargs)

    def problem(self, key: str, message: str) -> None:
        self.problems.append((key, message))


def candles_upto(count: int) -> list[Candle]:
    """49 candles at 60, one dip to 55 (index 49), then rises from 200."""
    closes = [Decimal(60)] * 49 + [Decimal(55)] + [
        Decimal(200 + index - 50) for index in range(50, count)
    ]
    return [
        Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + index * HOURLY,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=Decimal(1),
        )
        for index, close in enumerate(closes[:count])
    ]


def db_signals(db):
    from sqlalchemy import select

    from trendbot.database.models import Signal

    with db.session() as session:
        return session.scalars(select(Signal)).all()


def make_runner(db, notifier=None, clock=None) -> PaperLoopRunner:
    # Injectable clock: the risk gate correctly rejects entries evaluated
    # against stale data, so `now` must track the newest candle (the step
    # helper advances it as candles complete).
    return PaperLoopRunner(
        db,
        notifier=notifier,
        products=("BTC-USD",),
        now_provider=(lambda: clock["now"]) if clock else None,
    )


def step(db, runner: PaperLoopRunner, count: int, clock: dict | None = None) -> str | None:
    """Add candles up to `count` total, then run one loop cycle."""
    all_candles = candles_upto(count)
    stored = CandleRepository(db).get_range("BTC-USD", "ONE_HOUR", START, START + count * HOURLY)
    fresh = all_candles[len(stored):]
    if fresh:
        CandleRepository(db).upsert_many(fresh)
    if clock is not None:
        clock["now"] = START + count * HOURLY  # moment the newest candle completed
    return runner.cycle()


class TestRunnerLifecycle:
    def test_no_config_idles_but_stays_alive(self, db):
        runner = make_runner(db)
        assert runner.cycle() is None
        assert runner.status.running is False

    def test_config_builds_engine_and_seeds_window(self, db):
        StrategyEngine(db).set_config(
            product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0
        )
        runner = make_runner(db)
        result = step(db, runner, 50)
        assert result == "seeded"
        assert runner.status.running is True
        assert runner.status.last_processed_candle is not None

    def test_config_change_rebuilds_engine(self, db):
        StrategyEngine(db).set_config(
            product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0
        )
        runner = make_runner(db)
        step(db, runner, 50)

        StrategyEngine(db).set_config(
            product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=80.0
        )
        result = runner.cycle()
        assert result == "seeded"  # fresh window seeded for the new config
        assert "strategy config" in str(runner.status.details.get("last_config_change"))


class TestAutomatedTrade:
    def test_crossover_buys_and_notifies_without_any_manual_step(self, db):
        """The Sprint 15 acceptance path: signal → intent → fill → email."""
        notifier = RecordingNotifier()
        StrategyEngine(db).set_config(
            product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0
        )
        clock = {"now": START}
        runner = make_runner(db, notifier=notifier, clock=clock)

        step(db, runner, 50, clock)  # seed: flat run + dip
        assert runner.status.last_decision in (None, "hold")
        step(db, runner, 51, clock)  # jump candle → automated BUY decision
        assert runner.status.last_decision == "buy"
        step(db, runner, 52, clock)  # fill at next open

        # The intent walked the full state machine (filled = resolved).
        assert OrderIntentRepository(db).list_unresolved() == []
        # The automated decision is persisted for the dashboard history.
        signals = db_signals(db)
        assert any(row.decision == "buy" for row in signals)
        position = PositionRepository(db).get("BTC-USD")
        assert position is not None
        assert position.size == Decimal("2.5")
        assert runner.status.position_size == "2.5"

        # The fill triggered an order notification (email body inputs).
        assert len(notifier.fills) == 1
        fill = notifier.fills[0]
        assert fill["side"] == "buy"
        assert fill["mode"] == "paper"

    def test_notifier_disabled_leaves_trading_intact(self, db):
        StrategyEngine(db).set_config(
            product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0
        )
        clock = {"now": START}
        runner = make_runner(db, notifier=None, clock=clock)
        step(db, runner, 50, clock)
        step(db, runner, 51, clock)
        step(db, runner, 52, clock)
        assert Decimal(str(runner.status.position_size)) > 0


class TestRollupIntegration:
    def test_hourly_config_evaluates_derived_candles(self, db):
        """A 1h config works from 5m candles alone: the loop derives hours."""
        repo = CandleRepository(db)
        # Seed 5m candles for 60 hours (flat + dip + jump) at 12 per hour.
        for index in range(60):
            hour_start = START + index * HOURLY
            level = 60 if index < 49 else (55 if index == 49 else 200 + index - 50)
            repo.upsert_many(
                [
                    Candle(
                        product_id="BTC-USD",
                        granularity="FIVE_MINUTE",
                        start_time=hour_start + timedelta(minutes=5 * sub),
                        open=Decimal(level),
                        high=Decimal(level + 1),
                        low=Decimal(level - 1),
                        close=Decimal(level),
                        volume=Decimal(1),
                    )
                    for sub in range(12)
                ],
                source="exchange",
            )

        StrategyEngine(db).set_config(
            product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0
        )
        runner = make_runner(db)
        # The rollup catches up at most 48 hours per cycle (burst cap), so a
        # couple of cycles derive all 59 complete hours before seeding.
        runner.cycle()
        runner.cycle()
        derived = repo.get_range("BTC-USD", "ONE_HOUR", START, START + 60 * HOURLY)
        assert len(derived) >= 55
        # Next cycle processes the newest derived hour as a live candle.
        runner.cycle()
        assert runner.status.running is True
        assert runner.status.last_processed_candle is not None
