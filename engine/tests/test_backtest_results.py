"""Tests for the OOS split, export, and run persistence (Sprint 7 tasks 7-8)."""

import csv
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.backtesting.engine import BacktestEngine
from trendbot.backtesting.results import (
    export_results_json,
    export_trades_csv,
    split_in_sample_out_of_sample,
)
from trendbot.database import Database, upgrade_to_head
from trendbot.database.repositories import BacktestRepository, StrategyConfigRepository
from trendbot.market_data.candles import Candle
from trendbot.strategies.config import EmaRsiConfig

START = datetime(2026, 1, 1, tzinfo=UTC)


def rising_candles(count: int) -> list[Candle]:
    return [
        Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + index * timedelta(hours=1),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=Decimal(1),
        )
        for index in range(count)
    ]


class TestSplit:
    def test_seventy_thirty_split_is_chronological_and_disjoint(self):
        candles = rising_candles(10)
        in_sample, out_of_sample = split_in_sample_out_of_sample(candles, 0.7)
        assert len(in_sample) == 7 and len(out_of_sample) == 3
        assert in_sample[-1].start_time < out_of_sample[0].start_time
        assert in_sample[0].start_time == START
        assert out_of_sample[-1].start_time == START + timedelta(hours=9)

    def test_fraction_bounds_are_enforced(self):
        candles = rising_candles(10)
        with pytest.raises(ValueError):
            split_in_sample_out_of_sample(candles, 0.0)
        with pytest.raises(ValueError):
            split_in_sample_out_of_sample(candles, 1.0)

    def test_tiny_datasets_cannot_split(self):
        with pytest.raises(ValueError):
            split_in_sample_out_of_sample(rising_candles(1), 0.7)


class TestExport:
    @staticmethod
    def run_result() -> object:
        runner = BacktestEngine(
            strategy=_Scripted({0: "buy"}),
            assumptions=FeeAssumptions(fee_bps=100.0),
            initial_quote=Decimal("1000"),
            position_size_quote=Decimal("500"),
        )
        return runner.run(rising_candles(4), EmaRsiConfig(product_id="BTC-USD", timeframe="1h"))

    def test_json_export_contains_summary_equity_and_trades(self, tmp_path):
        result = self.run_result()
        path = export_results_json(result, tmp_path / "exports" / "run.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["trade_count"] >= 1
        assert len(payload["equity_curve"]) == 4
        assert payload["trades"][0]["entry_price"]

    def test_csv_export_has_header_and_ledger_rows(self, tmp_path):
        result = self.run_result()
        path = export_trades_csv(result, tmp_path / "exports" / "trades.csv")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        assert rows[0][0] == "entry_time"
        assert len(rows) == 1 + result.metrics.trade_count


class _Scripted:
    from trendbot.strategies.base import Strategy  # local import for typing only

    name = "scripted"
    version = "0.0.1"

    def __init__(self, actions: dict[int, str]) -> None:
        self._actions = actions

    def validate_config(self, config: object) -> None:
        return None

    def required_history(self, config: object) -> int:
        return 1

    def evaluate(self, candles: list[Candle], config: object, position: object = None) -> object:
        from trendbot.strategies.decisions import SignalType, StrategyDecision

        signal = SignalType(self._actions.get(len(candles) - 1, "hold"))
        return StrategyDecision(
            product_id=candles[-1].product_id,
            timeframe="1h",
            candle_time=candles[-1].start_time,
            signal=signal,
            reason_code="scripted",
            explanation="",
            indicator_values={},
            strategy_name=self.name,
            strategy_version=self.version,
            config_hash="scripted",
        )


class TestPersistence:
    def test_runs_and_trades_persist_and_list(self, tmp_path):
        database = Database(tmp_path / "bt.db")
        upgrade_to_head(database)
        config = EmaRsiConfig(product_id="BTC-USD", timeframe="1h")
        config_row = StrategyConfigRepository(database).get_or_create(
            name="ema_rsi_baseline",
            config_json={"product_id": "BTC-USD", "timeframe": "1h"},
            config_hash=config.config_hash(),
        )
        repo = BacktestRepository(database)
        runner = BacktestEngine(
            strategy=_Scripted({0: "buy"}),
            assumptions=FeeAssumptions(fee_bps=100.0),
            initial_quote=Decimal("1000"),
            position_size_quote=Decimal("500"),
        )
        result = runner.run(rising_candles(4), config)
        run_id = repo.record_run(
            strategy_config_id=config_row.id,
            product_id="BTC-USD",
            timeframe="1h",
            start_time=result.candles_from,
            end_time=result.candles_to,
            assumptions={"fee_bps": 100.0},
            metrics={"net_return_pct": str(result.metrics.net_return_pct)},
        )
        for trade in result.trades:
            repo.record_trade(run_id, trade)

        runs = repo.list_runs()
        assert len(runs) == 1
        assert runs[0].id == run_id
        assert runs[0].product_id == "BTC-USD"
        trades = repo.trades_for(run_id)
        assert len(trades) == result.metrics.trade_count
        assert trades[0].side == "long"

    def test_get_or_create_never_touches_the_active_config(self, tmp_path):
        database = Database(tmp_path / "cfg.db")
        upgrade_to_head(database)
        configs = StrategyConfigRepository(database)
        configs.save_active(
            name="ema_rsi_baseline",
            config_json={"product_id": "BTC-USD", "timeframe": "1h"},
            config_hash="hash-active",
        )
        row = configs.get_or_create(
            name="ema_rsi_baseline",
            config_json={"product_id": "BTC-USD", "timeframe": "4h"},
            config_hash="hash-backtest",
        )
        assert row.config_hash == "hash-backtest"
        assert row.is_active is False
        still_active = configs.get_active("ema_rsi_baseline")
        assert still_active is not None
        assert still_active.config_hash == "hash-active"
