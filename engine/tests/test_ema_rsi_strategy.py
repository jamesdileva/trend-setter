"""Baseline strategy scenario tests with exact hand-constructed candles (Sprint 6).

Every scenario is constructed so the indicator relationships at the last
candle are mathematically certain (flat series keep EMAs exactly at the
constant), giving deterministic BUY/SELL/HOLD outcomes without approximation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.market_data.candles import Candle
from trendbot.strategies.config import EmaRsiConfig, StrategyConfigError
from trendbot.strategies.decisions import SignalType, StrategyPosition
from trendbot.strategies.ema_rsi import EmaRsiStrategy, detect_crossover
from trendbot.strategies.registry import available_strategies, get_strategy

HOURLY = timedelta(hours=1)
START = datetime(2026, 1, 1, tzinfo=UTC)


def flat_then(*tail: float, base: float = 60.0, count: int = 49) -> list[Candle]:
    """`count` closes at `base`, then the tail closes, hourly from START."""
    closes = [Decimal(base)] * count + [Decimal(value) for value in tail]
    return [
        Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + index * HOURLY,
            open=close,
            high=close + Decimal(1),
            low=close - Decimal(1),
            close=close,
            volume=Decimal("1"),
        )
        for index, close in enumerate(closes)
    ]


def config(**overrides) -> EmaRsiConfig:
    values: dict[str, object] = {
        "product_id": "BTC-USD",
        "timeframe": "1h",
        "rsi_entry_ceiling": 97.0,  #BUY scenario: RSI computes to ≈96.9 after the jump
    }
    values.update(overrides)
    return EmaRsiConfig(**values)


class TestCrossoverDetection:
    def test_bullish_cross_requires_an_exact_transition(self):
        fast = [1.0, 1.0, 3.0]
        slow = [2.0, 2.0, 2.0]
        assert detect_crossover(fast, slow) == "bullish"

    def test_already_above_is_not_a_cross(self):
        assert detect_crossover([3.0, 3.0, 3.5], [2.0, 2.0, 2.0]) is None
        assert detect_crossover([3.0, 4.0, 3.5], [2.0, 2.0, 2.0]) is None

    def test_bearish_cross(self):
        assert detect_crossover([3.0, 3.0, 1.0], [2.0, 2.0, 2.0]) == "bearish"

    def test_warmup_nones_at_t_minus_one_prevent_a_cross(self):
        assert detect_crossover([None, None, 3.0], [None, None, 2.0]) is None


class TestScenarios:
    def test_bullish_crossover_with_rsi_below_ceiling_buys(self):
        # 49 candles at 60 (EMAs exactly 60), one drop to 55, then a jump to
        # 200: the fast EMA crosses above the slow EMA exactly on the last
        # candle, and RSI computes to ≈96.9 — below the 97 ceiling.
        decision = EmaRsiStrategy().evaluate(flat_then(55.0, 200.0), config())
        assert decision.signal == SignalType.BUY
        assert decision.reason_code == "bullish_crossover_rsi_ok"
        assert decision.candle_time == START + 50 * HOURLY
        assert decision.config_hash == config().config_hash()
        assert decision.strategy_name == "ema_rsi_baseline"

    def test_bullish_crossover_blocked_by_rsi_ceiling(self):
        decision = EmaRsiStrategy().evaluate(
            flat_then(55.0, 200.0), config(rsi_entry_ceiling=70.0)
        )
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "bullish_crossover_rsi_blocked"
        assert "96.9" in decision.explanation or "96" in decision.explanation

    def test_bearish_crossover_sells_without_rsi_condition(self):
        # Drop then deeper drop: fast crosses below slow exactly on the last
        # candle; exits never consult the RSI filter.
        decision = EmaRsiStrategy().evaluate(flat_then(65.0, 50.0), config())
        assert decision.signal == SignalType.SELL
        assert decision.reason_code == "bearish_crossover"

    def test_bearish_cross_while_long_is_an_exit(self):
        decision = EmaRsiStrategy().evaluate(
            flat_then(65.0, 50.0),
            config(),
            position=StrategyPosition(side="long", size=Decimal("1")),
        )
        assert decision.signal == SignalType.SELL
        assert decision.reason_code == "bearish_crossover_exit"

    def test_no_crossover_holds(self):
        # Continued decline: fast already below slow at t-1 and t — no transition.
        decision = EmaRsiStrategy().evaluate(flat_then(55.0, 53.0), config())
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "no_crossover"

    def test_sustained_uptrend_does_not_re_buy_every_candle(self):
        # Long flat run, one jump (cross happens), then continued rises:
        # after the first cross candle there is no new transition → HOLD.
        closes = flat_then(55.0, 200.0) + [
            Candle(
                product_id="BTC-USD",
                granularity="ONE_HOUR",
                start_time=START + (50 + index) * HOURLY,
                open=Decimal(200 + index + 1),
                high=Decimal(201 + index + 1),
                low=Decimal(199 + index + 1),
                close=Decimal(200 + index + 1),
                volume=Decimal("1"),
            )
            for index in range(3)
        ]
        decision = EmaRsiStrategy().evaluate(closes, config())
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code in ("no_crossover", "bullish_crossover_rsi_blocked")

    def test_insufficient_history_returns_an_explicit_hold(self):
        decision = EmaRsiStrategy().evaluate(flat_then(55.0, 200.0)[:40], config())
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "insufficient_history"
        assert "history" in decision.explanation

    def test_duplicate_entry_while_long_becomes_hold(self):
        decision = EmaRsiStrategy().evaluate(
            flat_then(55.0, 200.0),
            config(),
            position=StrategyPosition(side="long", size=Decimal("0.5")),
        )
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "already_in_position"

    def test_rsi_exit_floor_fires_while_long_without_a_crossover(self):
        decision = EmaRsiStrategy().evaluate(
            flat_then(55.0, 53.0),
            config(rsi_exit_floor=30.0),
            position=StrategyPosition(side="long", size=Decimal("0.5")),
        )
        assert decision.signal == SignalType.SELL
        assert decision.reason_code == "rsi_exit_floor"

    def test_rsi_exit_floor_does_not_fire_when_flat(self):
        decision = EmaRsiStrategy().evaluate(flat_then(55.0, 53.0), config(rsi_exit_floor=30.0))
        assert decision.signal == SignalType.HOLD
        assert decision.reason_code == "no_crossover"

    def test_incomplete_candles_are_rejected(self):
        candles = flat_then(55.0, 200.0)
        intruder = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + 99 * HOURLY,
            open=Decimal(100),
            high=Decimal(101),
            low=Decimal(99),
            close=Decimal(100),
            volume=Decimal(1),
            is_complete=False,
        )
        with pytest.raises(ValueError):
            EmaRsiStrategy().evaluate([*candles, intruder], config())

    def test_empty_input_is_rejected(self):
        with pytest.raises(ValueError):
            EmaRsiStrategy().evaluate([], config())

    def test_deterministic_repeated_evaluation(self):
        candles = flat_then(55.0, 200.0)
        first = EmaRsiStrategy().evaluate(candles, config())
        second = EmaRsiStrategy().evaluate(candles, config())
        assert first == second


class TestConfigHash:
    def test_identical_configs_share_the_hash(self):
        assert config().config_hash() == config().config_hash()

    def test_changing_a_parameter_changes_the_hash(self):
        assert config().config_hash() != config(rsi_entry_ceiling=90.0).config_hash()
        assert config().config_hash() != config(product_id="ETH-USD").config_hash()

    def test_exit_floor_changes_the_hash(self):
        assert config().config_hash() != config(rsi_exit_floor=30.0).config_hash()


class TestConfigValidation:
    def test_exit_floor_must_be_in_range(self):
        with pytest.raises(StrategyConfigError):
            config(rsi_exit_floor=150.0).require_valid()
        with pytest.raises(StrategyConfigError):
            config(rsi_exit_floor=-1.0).require_valid()

    def test_exit_floor_none_is_valid(self):
        config(rsi_exit_floor=None).require_valid()

    def test_invalid_config_rejects_evaluation(self):
        broken = EmaRsiConfig(
            product_id="BTC-USD",
            timeframe="1h",
            fast_ema_period=50,
            slow_ema_period=20,
        )
        with pytest.raises(StrategyConfigError):
            EmaRsiStrategy().evaluate(flat_then(55.0, 200.0), broken)


class TestRegistry:
    def test_baseline_is_registered(self):
        assert "ema_rsi_baseline" in available_strategies()
        assert isinstance(get_strategy("ema_rsi_baseline"), EmaRsiStrategy)

    def test_unknown_strategy_error_is_plain_language(self):
        with pytest.raises(KeyError) as excinfo:
            get_strategy("moon_launcher")
        assert "not registered" in str(excinfo.value)
        assert "ema_rsi_baseline" in str(excinfo.value)
