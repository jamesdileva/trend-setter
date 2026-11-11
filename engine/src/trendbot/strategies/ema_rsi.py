"""Baseline strategy: EMA crossover + RSI filter (architecture.md §8).

Exact semantics (implementation.md §8):

- bullish cross at completed candle ``t``: ``fast[t-1] <= slow[t-1]`` and
  ``fast[t] > slow[t]``; bearish is the mirror image;
- entry candidate: bullish cross AND RSI below the configured entry
  ceiling. A bullish cross blocked by the filter becomes an explicit HOLD
  with its own reason — never a silent drop;
- exit candidate: bearish cross (RSI is not a condition for exits), or the
  optional RSI exit floor while in a position (disabled by default);
- duplicate-entry guard: a BUY while already long becomes HOLD;
- insufficient history → HOLD with an explicit reason (no signal).

Baseline defaults (fast 20 / slow 50 / RSI 14 / ceiling 70) are starting
values from the roadmap — not optimized or recommended settings.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, TypedDict

from trendbot.market_data.candles import Candle
from trendbot.strategies.base import Strategy
from trendbot.strategies.config import EmaRsiConfig, StrategyConfigError
from trendbot.strategies.decisions import (
    FLAT_POSITION,
    SignalType,
    StrategyDecision,
    StrategyPosition,
)
from trendbot.strategies.indicators.ema import ema
from trendbot.strategies.indicators.rsi import rsi

BULLISH = "bullish"
BEARISH = "bearish"


def detect_crossover(
    fast: list[float | None], slow: list[float | None]
) -> str | None:
    """Classify the crossover at the last index: BULLISH/BEARISH/None.

    Both indicator values at ``t - 1`` and ``t`` must be present
    (post-warm-up); a cross at ``t`` requires the relation to flip exactly
    on that candle — an already-above/below pair is not a cross.
    """
    if len(fast) != len(slow) or len(fast) < 2:
        return None
    previous_fast, previous_slow = fast[-2], slow[-2]
    current_fast, current_slow = fast[-1], slow[-1]
    if None in (previous_fast, previous_slow, current_fast, current_slow):
        return None
    assert previous_fast is not None and previous_slow is not None
    assert current_fast is not None and current_slow is not None
    if previous_fast <= previous_slow and current_fast > current_slow:
        return BULLISH
    if previous_fast >= previous_slow and current_fast < current_slow:
        return BEARISH
    return None


class _DecisionBase(TypedDict):
    """Fields every decision of this strategy shares."""

    product_id: str
    timeframe: str
    candle_time: datetime
    indicator_values: dict[str, str]
    strategy_name: str
    strategy_version: str
    config_hash: str


class EmaRsiStrategy(Strategy):
    """Configurable EMA crossover + RSI filter (per product/timeframe)."""

    name: ClassVar[str] = "ema_rsi_baseline"
    version: ClassVar[str] = "1.0.0"

    def validate_config(self, config: object) -> None:
        if not isinstance(config, EmaRsiConfig):
            raise StrategyConfigError(
                "This strategy requires an EmaRsiConfig configuration."
            )
        config.require_valid()

    def required_history(self, config: object) -> int:
        assert isinstance(config, EmaRsiConfig)
        # EMA needs slow+1 closes for a cross at t (values at t-1 and t);
        # RSI needs rsi_period+2 closes for a value at t-1.
        return max(config.slow_ema_period + 1, config.rsi_period + 2)

    def evaluate(
        self,
        candles: list[Candle],
        config: object,
        position: StrategyPosition | None = None,
    ) -> StrategyDecision:
        assert isinstance(config, EmaRsiConfig)
        self.validate_config(config)
        if not candles:
            raise ValueError("Evaluation requires at least one completed candle.")
        if any(not candle.is_complete for candle in candles):
            raise ValueError(
                "Strategies may only evaluate completed candles; "
                "the input contains incomplete candles."
            )

        decision_candle = candles[-1]
        if len(candles) < self.required_history(config):
            return self._decision(
                self._base(decision_candle, config, {}),
                signal=SignalType.HOLD,
                reason_code="insufficient_history",
                explanation=(
                    f"Not enough candle history yet for {config.product_id} at "
                    f"{config.timeframe} (need {self.required_history(config)} candles "
                    f"before signals are enabled; have {len(candles)}). No signal."
                ),
            )

        closes = [candle.close for candle in candles]
        fast_series = ema(closes, config.fast_ema_period)
        slow_series = ema(closes, config.slow_ema_period)
        rsi_series = rsi(closes, config.rsi_period)
        crossover = detect_crossover(fast_series, slow_series)

        base = self._base(
            decision_candle,
            config,
            self._evidence(fast_series, slow_series, rsi_series),
        )
        rsi_now = rsi_series[-1]
        known_position = position if position is not None else FLAT_POSITION

        if crossover is None:
            # Optional protective exit: RSI floor while in a position,
            # even without a crossover (disabled by default).
            if (
                known_position.side == "long"
                and config.rsi_exit_floor is not None
                and rsi_now is not None
                and rsi_now < config.rsi_exit_floor
            ):
                return self._decision(
                    base,
                    signal=SignalType.SELL,
                    reason_code="rsi_exit_floor",
                    explanation=(
                        f"RSI ({rsi_now:.1f}) fell below the configured exit floor "
                        f"({config.rsi_exit_floor:g}) while a position is open — "
                        "exit candidate."
                    ),
                )
            return self._decision(
                base,
                signal=SignalType.HOLD,
                reason_code="no_crossover",
                explanation=self._no_cross_explanation(config),
            )

        if crossover == BULLISH:
            if known_position.side == "long":
                return self._decision(
                    base,
                    signal=SignalType.HOLD,
                    reason_code="already_in_position",
                    explanation=(
                        "A buy was signaled but a position is already open; "
                        "nothing new to do."
                    ),
                )
            if rsi_now is not None and rsi_now >= config.rsi_entry_ceiling:
                return self._decision(
                    base,
                    signal=SignalType.HOLD,
                    reason_code="bullish_crossover_rsi_blocked",
                    explanation=(
                        f"A bullish crossover occurred but RSI ({rsi_now:.1f}) is at or "
                        f"above the entry ceiling ({config.rsi_entry_ceiling:g}). No entry."
                    ),
                )
            return self._decision(
                base,
                signal=SignalType.BUY,
                reason_code="bullish_crossover_rsi_ok",
                explanation=(
                    "Bullish crossover: the fast EMA moved above the slow EMA and RSI "
                    "passed the entry filter."
                ),
            )

        # BEARISH: exits do not consult the RSI filter.
        if known_position.side == "long":
            return self._decision(
                base,
                signal=SignalType.SELL,
                reason_code="bearish_crossover_exit",
                explanation=(
                    "Bearish crossover: the fast EMA moved below the slow EMA while a "
                    "position is open — exit candidate."
                ),
            )
        return self._decision(
            base,
            signal=SignalType.SELL,
            reason_code="bearish_crossover",
            explanation=(
                "Bearish crossover: the fast EMA moved below the slow EMA. "
                "Exit candidate (no open position to exit)."
            ),
        )

    def _base(
        self,
        candle: Candle,
        config: EmaRsiConfig,
        evidence: dict[str, str],
    ) -> _DecisionBase:
        return {
            "product_id": candle.product_id,
            "timeframe": config.timeframe,
            "candle_time": candle.start_time,
            "indicator_values": evidence,
            "strategy_name": self.name,
            "strategy_version": self.version,
            "config_hash": config.config_hash(),
        }

    @staticmethod
    def _decision(
        base: _DecisionBase,
        *,
        signal: SignalType,
        reason_code: str,
        explanation: str,
    ) -> StrategyDecision:
        return StrategyDecision(
            product_id=base["product_id"],
            timeframe=base["timeframe"],
            candle_time=base["candle_time"],
            signal=signal,
            reason_code=reason_code,
            explanation=explanation,
            indicator_values=base["indicator_values"],
            strategy_name=base["strategy_name"],
            strategy_version=base["strategy_version"],
            config_hash=base["config_hash"],
        )

    @staticmethod
    def _no_cross_explanation(config: EmaRsiConfig) -> str:
        return (
            "No crossover on this candle: the fast EMA and slow EMA kept their previous "
            f"relationship. Holding. (fast={config.fast_ema_period}, slow={config.slow_ema_period})"
        )

    @staticmethod
    def _evidence(
        fast_series: list[float | None],
        slow_series: list[float | None],
        rsi_series: list[float | None],
    ) -> dict[str, str]:
        def fmt(value: float | None) -> str:
            return "n/a" if value is None else f"{value:.8f}"

        return {
            "fast_ema": fmt(fast_series[-1]),
            "slow_ema": fmt(slow_series[-1]),
            "rsi": fmt(rsi_series[-1]),
        }
