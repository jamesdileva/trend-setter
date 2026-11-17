"""Strategy registry: name → strategy implementation (implementation.md §8)."""

from __future__ import annotations

from trendbot.strategies.base import Strategy
from trendbot.strategies.config import DONCHIAN_STRATEGY_NAME, STRATEGY_NAME
from trendbot.strategies.donchian import DonchianStrategy
from trendbot.strategies.ema_rsi import EmaRsiStrategy

_REGISTRY: dict[str, type[Strategy]] = {
    STRATEGY_NAME: EmaRsiStrategy,
    DONCHIAN_STRATEGY_NAME: DonchianStrategy,
}


def get_strategy(name: str) -> Strategy:
    """Return the strategy registered under ``name`` (plain error if unknown)."""
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(
            f"Strategy {name!r} is not registered. "
            f"Available strategies: {', '.join(sorted(_REGISTRY))}."
        ) from None


def available_strategies() -> list[str]:
    return sorted(_REGISTRY)
