"""Donchian-channel breakout strategy (the classic trend-follower).

Semantics (Sprint 16):

- ENTRY: the completed candle's close exceeds the highest high of the prior
  ``entry_lookback`` candles (the current candle is excluded from its own
  channel) → BUY candidate, when flat.
- EXIT: the completed candle's close falls below the lowest low of the prior
  ``exit_lookback`` candles (exit channel shorter than the entry channel,
  turtle-style) → SELL candidate, when long.
- Everything else is HOLD with an explicit reason; insufficient history is a
  HOLD, never a silent drop. No indicator filter — the channel IS the filter.

Compared with the EMA crossover, breakouts enter LATE (on new highs) and
exit on structure rather than on a moving-average cross. Whipsaw shows up as
repeated failed breakouts in chop; the turtle exit cuts losers faster.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar, TypedDict

from trendbot.market_data.candles import Candle
from trendbot.strategies.base import Strategy
from trendbot.strategies.config import DonchianConfig, StrategyConfigError
from trendbot.strategies.decisions import (
    FLAT_POSITION,
    SignalType,
    StrategyDecision,
    StrategyPosition,
)


class _DecisionBase(TypedDict):
    """Fields every decision of this strategy shares."""

    product_id: str
    timeframe: str
    candle_time: datetime
    indicator_values: dict[str, str]
    strategy_name: str
    strategy_version: str
    config_hash: str


def channel_levels(
    candles: list[Candle], *, entry_lookback: int, exit_lookback: int
) -> tuple[Decimal, Decimal]:
    """(entry_level, exit_level) for the decision candle at ``candles[-1]``.

    The levels come from the candles BEFORE the decision candle — a channel
    that includes the current candle could never be "broken" by it.
    """
    entry_highs = candles[-(entry_lookback + 1) : -1]
    exit_lows = candles[-(exit_lookback + 1) : -1]
    entry_level = max(candle.high for candle in entry_highs)
    exit_level = min(candle.low for candle in exit_lows)
    return entry_level, exit_level


class DonchianStrategy(Strategy):
    """Breakout above the N-candle high; exit below the M-candle low."""

    name: ClassVar[str] = "donchian_breakout"
    version: ClassVar[str] = "1.0.0"

    def validate_config(self, config: object) -> None:
        if not isinstance(config, DonchianConfig):
            raise StrategyConfigError(
                "This strategy requires a DonchianConfig configuration."
            )
        config.require_valid()

    def required_history(self, config: object) -> int:
        assert isinstance(config, DonchianConfig)
        # The entry channel needs entry_lookback candles before the decision
        # candle; the exit channel is shorter by validation.
        return config.entry_lookback + 1

    def evaluate(
        self,
        candles: list[Candle],
        config: object,
        position: StrategyPosition | None = None,
    ) -> StrategyDecision:
        assert isinstance(config, DonchianConfig)
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

        entry_level, exit_level = channel_levels(
            candles,
            entry_lookback=config.entry_lookback,
            exit_lookback=config.exit_lookback,
        )
        close = decision_candle.close
        known_position = position if position is not None else FLAT_POSITION

        base = self._base(
            decision_candle,
            config,
            {
                "entry_level": f"{entry_level}",
                "exit_level": f"{exit_level}",
                "close": f"{close}",
            },
        )

        if known_position.side == "long":
            if close < exit_level:
                return self._decision(
                    base,
                    signal=SignalType.SELL,
                    reason_code="breakdown_below_exit_channel",
                    explanation=(
                        f"The close ({close}) fell below the lowest low of the last "
                        f"{config.exit_lookback} candles ({exit_level}) — exit the "
                        "position."
                    ),
                )
            return self._decision(
                base,
                signal=SignalType.HOLD,
                reason_code="holding_inside_channel",
                explanation=(
                    f"Holding: the close ({close}) is still inside the exit channel "
                    f"(above {exit_level})."
                ),
            )

        # Flat: look for an entry breakout.
        if close > entry_level:
            return self._decision(
                base,
                signal=SignalType.BUY,
                reason_code="breakout_above_entry_channel",
                explanation=(
                    f"Breakout: the close ({close}) rose above the highest high of the "
                    f"last {config.entry_lookback} candles ({entry_level})."
                ),
            )
        if close < exit_level:
            return self._decision(
                base,
                signal=SignalType.HOLD,
                reason_code="breakdown_but_flat",
                explanation=(
                    f"The close ({close}) broke below the exit channel "
                    f"({exit_level}) but there is no position to exit."
                ),
            )
        return self._decision(
            base,
            signal=SignalType.HOLD,
            reason_code="inside_channel",
            explanation=(
                f"Holding flat: the close ({close}) is inside the entry channel "
                f"(below {entry_level})."
            ),
        )

    def _base(
        self,
        candle: Candle,
        config: DonchianConfig,
        indicator_values: dict[str, str],
    ) -> _DecisionBase:
        return {
            "product_id": config.product_id,
            "timeframe": config.timeframe,
            "candle_time": candle.start_time,
            "indicator_values": indicator_values,
            "strategy_name": self.name,
            "strategy_version": self.version,
            "config_hash": config.config_hash(),
        }

    def _decision(
        self,
        base: _DecisionBase,
        *,
        signal: SignalType,
        reason_code: str,
        explanation: str,
    ) -> StrategyDecision:
        return StrategyDecision(
            signal=signal,
            reason_code=reason_code,
            explanation=explanation,
            **base,
        )
