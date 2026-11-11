"""Strategy interface (architecture.md §8).

Strategies are deterministic components that consume validated,
completed candles and produce a decision. They cannot call the exchange,
submit orders, or import ``trendbot.exchange`` / ``trendbot.execution``
— an architecture test enforces the import ban.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from trendbot.market_data.candles import Candle
from trendbot.strategies.decisions import FLAT_POSITION, StrategyDecision, StrategyPosition


class Strategy(ABC):
    """Base class every strategy implements."""

    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"

    @abstractmethod
    def validate_config(self, config: object) -> None:
        """Raise :class:`StrategyConfigError` when the config is invalid."""

    @abstractmethod
    def required_history(self, config: object) -> int:
        """Minimum number of completed candles before signals are enabled."""

    @abstractmethod
    def evaluate(
        self,
        candles: list[Candle],
        config: object,
        position: StrategyPosition = FLAT_POSITION,
    ) -> StrategyDecision:
        """Evaluate the latest completed candle and return a decision.

        Implementations must be deterministic: identical inputs produce
        identical decisions. Config changes apply at the next completed
        candle (the caller evaluates per candle), never mid-bucket.
        """
