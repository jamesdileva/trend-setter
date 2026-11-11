"""Strategy engine: config lifecycle and decision evaluation (Sprint 6).

Glues the registry, the versioned config store, the candle repository,
and the signal repository together:

- ``set_config`` validates and stores a new active config version;
- ``evaluate`` loads enough stored candles, runs the registered strategy,
  and persists the decision (idempotent per candle).

Decisions are evidence only — this layer never submits orders, and
config changes apply at the next completed-candle evaluation.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import cast

from trendbot.database.repositories import (
    CandleRepository,
    SignalRepository,
    StrategyConfigRepository,
)
from trendbot.database.session import Database
from trendbot.market_data.granularity import granularity_for_timeframe, granularity_seconds
from trendbot.strategies.base import Strategy
from trendbot.strategies.config import STRATEGY_NAME, EmaRsiConfig
from trendbot.strategies.decisions import FLAT_POSITION, SignalType, StrategyDecision
from trendbot.strategies.registry import get_strategy


class StrategyNotConfiguredError(RuntimeError):
    """Raised when evaluation is requested before any config exists."""


class StrategyEngine:
    """Evaluates the registered baseline strategy over stored candles."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._configs = StrategyConfigRepository(database)
        self._signals = SignalRepository(database)
        self._candles = CandleRepository(database)

    def set_config(
        self,
        *,
        product_id: str,
        timeframe: str,
        fast_ema_period: int = 20,
        slow_ema_period: int = 50,
        rsi_period: int = 14,
        rsi_entry_ceiling: float = 70.0,
        rsi_exit_floor: float | None = None,
    ) -> dict[str, object]:
        """Validate and store a new active config version (plain errors on failure)."""
        config = EmaRsiConfig(
            product_id=product_id,
            timeframe=timeframe,
            fast_ema_period=fast_ema_period,
            slow_ema_period=slow_ema_period,
            rsi_period=rsi_period,
            rsi_entry_ceiling=rsi_entry_ceiling,
            rsi_exit_floor=rsi_exit_floor,
        )
        config.require_valid()
        strategy = self._strategy()
        strategy.validate_config(config)
        row = self._configs.save_active(
            name=STRATEGY_NAME,
            config_json=asdict(config),
            config_hash=config.config_hash(),
        )
        return {
            "status": "saved",
            "name": STRATEGY_NAME,
            "version": row.version,
            "config_hash": row.config_hash,
            "config": asdict(config),
        }

    def current_config(self) -> EmaRsiConfig | None:
        """The active configuration, or None when nothing is configured yet."""
        row = self._configs.get_active(STRATEGY_NAME)
        if row is None:
            return None
        return self._config_from_row(row.config_json)

    def evaluate(
        self, product_id: str | None = None, timeframe: str | None = None
    ) -> StrategyDecision:
        """Evaluate the latest completed candle and persist the decision.

        ``product_id``/``timeframe`` overrides select which stored candle
        series to evaluate (per-product/per-timeframe instances); the
        indicator parameters always come from the active config. Repeated
        evaluation of the same candle does not duplicate signal rows.
        """
        config = self.current_config()
        if config is None:
            raise StrategyNotConfiguredError(
                "No strategy is configured yet. Set the strategy parameters first."
            )
        strategy = self._strategy()
        product = product_id or config.product_id
        engine_timeframe = timeframe or config.timeframe
        granularity = granularity_for_timeframe(engine_timeframe)
        seconds = granularity_seconds(granularity)

        latest = self._candles.latest_complete_start(product, granularity)
        if latest is None:
            return self._no_data_decision(strategy, config, product, engine_timeframe)

        required = strategy.required_history(config)
        window_start = latest - timedelta(seconds=(required - 1) * seconds)
        candles = self._candles.get_range(
            product, granularity, window_start, latest + timedelta(seconds=1)
        )

        decision = strategy.evaluate(
            candles[-required:], config, position=FLAT_POSITION
        )
        if product_id is not None:
            decision = self._rebrand(decision, product_id, engine_timeframe)

        config_row = self._configs.get_by_hash(STRATEGY_NAME, decision.config_hash)
        if config_row is None:
            config_row = self._configs.save_active(
                name=STRATEGY_NAME,
                config_json=asdict(config),
                config_hash=decision.config_hash,
            )
        self._signals.record(decision, strategy_config_id=config_row.id)
        return decision

    def recent_signals(
        self, product_id: str, timeframe: str, limit: int = 20
    ) -> list[dict[str, object]]:
        granularity = granularity_for_timeframe(timeframe)
        rows = self._signals.recent(product_id, granularity, limit)
        return [
            {
                "candle_time": row.candle_start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "decision": row.decision,
                "reason_code": row.reason_code,
                "explanation": row.explanation,
                "strategy_version": row.strategy_version,
                "config_hash": row.config_hash,
            }
            for row in rows
        ]

    def _strategy(self) -> Strategy:
        return get_strategy(STRATEGY_NAME)

    @staticmethod
    def _config_from_row(config_json: dict[str, object]) -> EmaRsiConfig:
        return EmaRsiConfig(
            product_id=cast(str, config_json["product_id"]),
            timeframe=cast(str, config_json["timeframe"]),
            fast_ema_period=cast(int, config_json["fast_ema_period"]),
            slow_ema_period=cast(int, config_json["slow_ema_period"]),
            rsi_period=cast(int, config_json["rsi_period"]),
            rsi_entry_ceiling=cast(float, config_json["rsi_entry_ceiling"]),
            rsi_exit_floor=cast("float | None", config_json.get("rsi_exit_floor")),
        )

    @staticmethod
    def _rebrand(
        decision: StrategyDecision, product_id: str, timeframe: str
    ) -> StrategyDecision:
        """Re-point a decision at the requested product/timeframe instance."""
        return StrategyDecision(
            product_id=product_id,
            timeframe=timeframe,
            candle_time=decision.candle_time,
            signal=decision.signal,
            reason_code=decision.reason_code,
            explanation=decision.explanation,
            indicator_values=decision.indicator_values,
            strategy_name=decision.strategy_name,
            strategy_version=decision.strategy_version,
            config_hash=decision.config_hash,
        )

    @staticmethod
    def _no_data_decision(
        strategy: Strategy, config: EmaRsiConfig, product_id: str, timeframe: str
    ) -> StrategyDecision:
        return StrategyDecision(
            product_id=product_id,
            timeframe=timeframe,
            candle_time=datetime.now(UTC),
            signal=SignalType.HOLD,
            reason_code="no_data",
            explanation=(
                f"No completed candles stored for {product_id} at {timeframe} yet. "
                f"Import history or wait for the live feed (need at least "
                f"{strategy.required_history(config)} candles before signals)."
            ),
            indicator_values={},
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            config_hash=config.config_hash(),
        )
