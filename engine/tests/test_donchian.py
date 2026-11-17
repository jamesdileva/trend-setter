"""Donchian breakout strategy tests (Sprint 16)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.market_data.candles import Candle
from trendbot.strategies.config import DonchianConfig, StrategyConfigError
from trendbot.strategies.decisions import SignalType, StrategyPosition
from trendbot.strategies.donchian import DonchianStrategy

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
HOURLY = timedelta(hours=1)
LONG = StrategyPosition(side="long", size=Decimal("1"))


def candles(closes: list[int], *, complete: bool = True) -> list[Candle]:
    return [
        Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + index * HOURLY,
            open=Decimal(close),
            high=Decimal(close) + 1,
            low=Decimal(close) - 1,
            close=Decimal(close),
            volume=Decimal(1),
            is_complete=complete,
        )
        for index, close in enumerate(closes)
    ]


def config(**overrides) -> DonchianConfig:
    values = {"product_id": "BTC-USD", "timeframe": "1h"}
    values.update(overrides)
    return DonchianConfig(**values)


class TestBreakoutDecisions:
    def test_breakout_above_entry_channel_buys_when_flat(self):
        strategy = DonchianStrategy()
        # 20 candles at 100, then a close of 130 — above every prior high.
        history = candles([100] * 20 + [130])
        decision = strategy.evaluate(history, config(), position=None)
        assert decision.signal == SignalType.BUY
        assert decision.reason_code == "breakout_above_entry_channel"
        # The entry channel excludes the decision candle itself.
        assert decision.indicator_values["entry_level"] == "101"

    def test_close_inside_channel_holds_flat(self):
        strategy = DonchianStrategy()
        history = candles([100] * 20 + [100])
        decision = strategy.evaluate(history, config(), position=None)
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "inside_channel"

    def test_breakdown_while_flat_holds_with_explicit_reason(self):
        strategy = DonchianStrategy()
        history = candles([100] * 20 + [50])
        decision = strategy.evaluate(history, config(), position=None)
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "breakdown_but_flat"

    def test_channel_exit_sells_when_long(self):
        strategy = DonchianStrategy()
        # Lows sit at close-1; a close of 88 puts the low at 87, below the
        # lowest prior low (99).
        history = candles([100] * 20 + [88])
        decision = strategy.evaluate(history, config(), position=LONG)
        assert decision.signal == SignalType.SELL
        assert decision.reason_code == "breakdown_below_exit_channel"

    def test_long_inside_exit_channel_holds(self):
        strategy = DonchianStrategy()
        history = candles([100] * 20 + [105])
        decision = strategy.evaluate(history, config(), position=LONG)
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "holding_inside_channel"

    def test_insufficient_history_holds_with_reason(self):
        strategy = DonchianStrategy()
        history = candles([100] * 5)
        decision = strategy.evaluate(history, config(), position=None)
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "insufficient_history"

    def test_incomplete_candles_are_rejected(self):
        strategy = DonchianStrategy()
        history = candles([100] * 21, complete=False)
        with pytest.raises(ValueError, match="completed candles"):
            strategy.evaluate(history, config(), position=None)

    def test_required_history_is_entry_plus_one(self):
        assert DonchianStrategy().required_history(config()) == 21
        assert DonchianStrategy().required_history(config(entry_lookback=55)) == 56


class TestValidation:
    def test_exit_channel_must_be_shorter_than_entry(self):
        with pytest.raises(StrategyConfigError, match="shorter than the entry"):
            config(entry_lookback=10, exit_lookback=10).require_valid()

    def test_bounds_are_enforced(self):
        with pytest.raises(StrategyConfigError, match="entry lookback"):
            config(entry_lookback=4).require_valid()
        with pytest.raises(StrategyConfigError, match="exit lookback"):
            config(entry_lookback=20, exit_lookback=200).require_valid()

    def test_wrong_config_type_rejected(self):
        from trendbot.strategies.config import EmaRsiConfig

        with pytest.raises(StrategyConfigError, match="DonchianConfig"):
            DonchianStrategy().validate_config(
                EmaRsiConfig(product_id="BTC-USD", timeframe="1h")
            )

    def test_config_hash_reflects_parameters(self):
        base = config().config_hash()
        changed = config(entry_lookback=55, exit_lookback=20).config_hash()
        assert base != changed
        assert config().config_hash() == base  # deterministic
