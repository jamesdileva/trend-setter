"""Baseline strategy configuration model and validation.

Implements the configuration rules from ``architecture.md`` §8
(Configuration validation) and ``implementation.md`` §5:

- fast EMA period must be less than slow EMA period;
- indicator periods are positive whole numbers within validated bounds;
- product and timeframe must be from the supported set;
- rejections carry plain-language messages suitable for a nontechnical user.
"""

from __future__ import annotations

from dataclasses import dataclass

# Initial supported set from architecture.md §2 and §7.
SUPPORTED_PRODUCTS: tuple[str, ...] = ("BTC-USD", "ETH-USD")
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h")

# Validated bounds for indicator periods. Conservative until Sprint 0/6
# evidence justifies wider values.
MIN_EMA_PERIOD = 2
MAX_EMA_PERIOD = 400
MIN_RSI_PERIOD = 2
MAX_RSI_PERIOD = 200


class StrategyConfigError(ValueError):
    """Raised when a strategy configuration is invalid."""


@dataclass(frozen=True)
class EmaRsiConfig:
    """Configuration for the EMA crossover + RSI baseline strategy.

    Default periods are the baseline starting values from
    ``sprint-roadmap.md`` Sprint 6 — starting points, not optimized or
    recommended settings.
    """

    product_id: str
    timeframe: str
    fast_ema_period: int = 20
    slow_ema_period: int = 50
    rsi_period: int = 14
    rsi_entry_ceiling: float = 70.0

    def validate(self) -> list[str]:
        """Return every validation problem as a plain-language message.

        An empty list means the configuration is valid.
        """
        problems: list[str] = []

        if self.product_id not in SUPPORTED_PRODUCTS:
            problems.append(
                f"Product {self.product_id!r} is not supported. "
                f"Supported products: {', '.join(SUPPORTED_PRODUCTS)}."
            )

        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            problems.append(
                f"Timeframe {self.timeframe!r} is not supported. "
                f"Supported timeframes: {', '.join(SUPPORTED_TIMEFRAMES)}."
            )

        problems.extend(
            _check_period(
                "fast EMA period", self.fast_ema_period, MIN_EMA_PERIOD, MAX_EMA_PERIOD
            )
        )
        problems.extend(
            _check_period(
                "slow EMA period", self.slow_ema_period, MIN_EMA_PERIOD, MAX_EMA_PERIOD
            )
        )
        problems.extend(
            _check_period("RSI period", self.rsi_period, MIN_RSI_PERIOD, MAX_RSI_PERIOD)
        )

        if _is_int(self.fast_ema_period) and _is_int(self.slow_ema_period):
            if self.fast_ema_period >= self.slow_ema_period:
                problems.append(
                    "The fast EMA period must be less than the slow EMA period "
                    f"(fast: {self.fast_ema_period}, slow: {self.slow_ema_period})."
                )

        if not _is_number(self.rsi_entry_ceiling):
            problems.append("The RSI entry ceiling must be a number between 0 and 100 (exclusive).")
        elif not 0 < self.rsi_entry_ceiling < 100:
            problems.append("The RSI entry ceiling must be between 0 and 100 (exclusive).")

        return problems

    def require_valid(self) -> None:
        """Raise :class:`StrategyConfigError` listing every problem, if invalid."""
        problems = self.validate()
        if problems:
            raise StrategyConfigError(" ".join(problems))


def _is_int(value: object) -> bool:
    """True for real integers (bool is rejected even though it subclasses int)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_period(label: str, value: object, minimum: int, maximum: int) -> list[str]:
    # Inline narrowing (not _is_int) so type checkers see value as int here.
    if not isinstance(value, int) or isinstance(value, bool):
        return [f"The {label} must be a whole number between {minimum} and {maximum}."]
    if not minimum <= value <= maximum:
        return [f"The {label} must be between {minimum} and {maximum}."]
    return []
