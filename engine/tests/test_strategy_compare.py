"""Strategy comparison service tests (Sprint 16)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.application.backtest_service import InsufficientDataError
from trendbot.application.strategy_compare import compare_strategies
from trendbot.database import Database, upgrade_to_head
from trendbot.database.repositories import BacktestRepository, CandleRepository
from trendbot.market_data.candles import Candle

START = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
HOURLY = timedelta(hours=1)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "compare.db")
    upgrade_to_head(database)
    return database


def seed_candles(db, count: int = 400) -> None:
    """Up-trend into a range: enough history for every grid entry.

    Rises ~0.1% per candle for the first 240 candles (in-sample), then
    oscillates — so momentum candidates look good in-sample but the
    out-of-sample window is chop.
    """
    candles: list[Candle] = []
    level = Decimal(100)
    for index in range(count):
        if index < 240:
            level = level * Decimal("1.001")
        else:
            level = level * (Decimal("1.004") if index % 2 else Decimal("0.996"))
        candles.append(
            Candle(
                product_id="BTC-USD",
                granularity="ONE_HOUR",
                start_time=START + index * HOURLY,
                open=level,
                high=level * Decimal("1.002"),
                low=level * Decimal("0.998"),
                close=level,
                volume=Decimal(1),
            )
        )
    CandleRepository(db).upsert_many(candles)


class TestCompareStrategies:
    def test_ranks_every_registered_strategy_with_benchmark(self, db):
        seed_candles(db)
        result = compare_strategies(db, product_id="BTC-USD", timeframe="1h")

        names = {row["strategy_name"] for row in result["ranking"]}
        assert names == {"ema_rsi_baseline", "donchian_breakout"}
        assert len(result["ranking"]) == 9  # 6 EMA/RSI + 3 Donchian combos
        assert result["benchmark"] is not None
        assert result["benchmark"]["strategy_name"] == "buy_and_hold_benchmark"
        assert len(result["caveats"]) >= 3

    def test_ranking_is_by_out_of_sample_return_descending(self, db):
        seed_candles(db)
        result = compare_strategies(db, product_id="BTC-USD", timeframe="1h")
        oos = [Decimal(row["oos_net_return_pct"]) for row in result["ranking"]]
        assert oos == sorted(oos, reverse=True)

    def test_comparison_is_deterministic(self, db):
        seed_candles(db)
        first = compare_strategies(db, product_id="BTC-USD", timeframe="1h")
        second = compare_strategies(db, product_id="BTC-USD", timeframe="1h")
        assert first["ranking"] == second["ranking"]

    def test_sweep_does_not_pollute_the_runs_table(self, db):
        seed_candles(db)
        compare_strategies(db, product_id="BTC-USD", timeframe="1h")
        assert BacktestRepository(db).list_runs(limit=100) == []

    def test_low_oos_trade_counts_are_marked_weak(self, db):
        seed_candles(db)
        result = compare_strategies(db, product_id="BTC-USD", timeframe="1h")
        verdicts = {row["oos_verdict"] for row in result["ranking"]}
        assert verdicts <= {
            "meaningful sample",
            "few trades — weak evidence",
            "too few trades to judge",
        }

    def test_insufficient_data_raises_plain_language_error(self, db):
        CandleRepository(db).upsert_many(
            [
                Candle(
                    product_id="BTC-USD",
                    granularity="ONE_HOUR",
                    start_time=START,
                    open=Decimal(100),
                    high=Decimal(101),
                    low=Decimal(99),
                    close=Decimal(100),
                    volume=Decimal(1),
                )
            ]
        )
        with pytest.raises(InsufficientDataError):
            compare_strategies(db, product_id="BTC-USD", timeframe="1h")
