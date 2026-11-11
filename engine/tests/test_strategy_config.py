"""Tests for the baseline strategy configuration model (architecture.md §8)."""

import dataclasses

import pytest

from trendbot.strategies.config import (
    SUPPORTED_PRODUCTS,
    SUPPORTED_TIMEFRAMES,
    EmaRsiConfig,
    StrategyConfigError,
)


def make_config(**overrides: object) -> EmaRsiConfig:
    defaults: dict[str, object] = {"product_id": "BTC-USD", "timeframe": "1h"}
    defaults.update(overrides)
    return EmaRsiConfig(**defaults)


class TestSupportedSets:
    def test_supported_products_match_architecture(self):
        assert SUPPORTED_PRODUCTS == ("BTC-USD", "ETH-USD")

    def test_supported_timeframes_match_architecture(self):
        assert SUPPORTED_TIMEFRAMES == ("1m", "5m", "15m", "1h", "4h")


class TestValidConfiguration:
    def test_baseline_defaults_are_valid(self):
        config = make_config()
        assert config.validate() == []
        config.require_valid()  # must not raise

    def test_every_supported_combination_is_valid(self):
        for product in SUPPORTED_PRODUCTS:
            for timeframe in SUPPORTED_TIMEFRAMES:
                config = make_config(product_id=product, timeframe=timeframe)
                assert config.validate() == []

    def test_boundaries_of_period_ranges_are_valid(self):
        assert make_config(fast_ema_period=2, slow_ema_period=3, rsi_period=2).validate() == []
        assert (
            make_config(fast_ema_period=399, slow_ema_period=400, rsi_period=200).validate() == []
        )

    def test_config_is_immutable(self):
        config = make_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.fast_ema_period = 10


class TestInvalidConfiguration:
    @pytest.mark.parametrize("product_id", ["SOL-USD", "btc-usd", "", "BTC-USD ", "BTC-USDT"])
    def test_unsupported_products_are_rejected(self, product_id):
        problems = make_config(product_id=product_id).validate()
        assert any("not supported" in p and "Product" in p for p in problems)

    @pytest.mark.parametrize("timeframe", ["2m", "30m", "1d", "1H", ""])
    def test_unsupported_timeframes_are_rejected(self, timeframe):
        problems = make_config(timeframe=timeframe).validate()
        assert any("not supported" in p and "Timeframe" in p for p in problems)

    @pytest.mark.parametrize("field", ["fast_ema_period", "slow_ema_period", "rsi_period"])
    @pytest.mark.parametrize("bad_value", [0, -3, 1.5, "20", True, None])
    def test_bad_periods_are_rejected(self, field, bad_value):
        assert make_config(**{field: bad_value}).validate() != []

    def test_periods_below_minimum_are_rejected(self):
        assert make_config(fast_ema_period=1, slow_ema_period=2).validate() != []
        assert make_config(fast_ema_period=2, slow_ema_period=3, rsi_period=1).validate() != []

    def test_periods_above_maximum_are_rejected(self):
        assert make_config(fast_ema_period=401, slow_ema_period=402).validate() != []
        assert make_config(fast_ema_period=2, slow_ema_period=3, rsi_period=201).validate() != []

    def test_fast_ema_equal_to_slow_ema_is_rejected(self):
        problems = make_config(fast_ema_period=50, slow_ema_period=50).validate()
        assert any("less than the slow EMA" in p for p in problems)

    def test_fast_ema_greater_than_slow_ema_is_rejected(self):
        problems = make_config(fast_ema_period=50, slow_ema_period=20).validate()
        assert any("less than the slow EMA" in p for p in problems)

    @pytest.mark.parametrize("ceiling", [0, 100, -5, 150, "70", True, None])
    def test_bad_rsi_entry_ceilings_are_rejected(self, ceiling):
        problems = make_config(rsi_entry_ceiling=ceiling).validate()
        assert any("RSI entry ceiling" in p for p in problems)

    def test_require_valid_raises_with_plain_language_message(self):
        with pytest.raises(StrategyConfigError) as excinfo:
            make_config(fast_ema_period=50, slow_ema_period=20).require_valid()
        message = str(excinfo.value)
        assert "fast EMA period" in message
        assert "slow EMA period" in message
