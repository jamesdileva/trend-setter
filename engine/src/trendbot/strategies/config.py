"""Baseline strategy configuration model and validation.

Implements the configuration rules from ``architecture.md`` §8
(Configuration validation) and ``implementation.md`` §5:

- fast EMA period must be less than slow EMA period;
- indicator periods are positive whole numbers within validated bounds;
- product and timeframe must be from the supported set;
- rejections carry plain-language messages suitable for a nontechnical user.

``config_hash`` provides the per-config identity recorded on every signal
(architecture.md §8: "Record the active config version/hash with every
signal and order intent").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

# Initial supported set from architecture.md §2 and §7.
SUPPORTED_PRODUCTS: tuple[str, ...] = ("BTC-USD", "ETH-USD")
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h")

# Validated bounds for indicator periods. Conservative until Sprint 0/6
# evidence justifies wider values.
MIN_EMA_PERIOD = 2
MAX_EMA_PERIOD = 400
MIN_RSI_PERIOD = 2
MAX_RSI_PERIOD = 200

STRATEGY_NAME = "ema_rsi_baseline"
DONCHIAN_STRATEGY_NAME = "donchian_breakout"


class StrategyConfigError(ValueError):
    """Raised when a strategy configuration is invalid."""


class StrategyConfig(Protocol):
    """The config surface every strategy configuration provides.

    Strategies receive ``object`` configs and narrow to their own type; the
    pipeline (backtester, paper loop, storage) only relies on this surface.
    Members are read-only properties so frozen dataclasses satisfy it.
    """

    @property
    def product_id(self) -> str: ...

    @property
    def timeframe(self) -> str: ...

    def validate(self) -> list[str]: ...

    def require_valid(self) -> None: ...

    def config_hash(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class EmaRsiConfig:
    """Configuration for the EMA crossover + RSI baseline strategy.

    Default periods are the baseline starting values from
    ``sprint-roadmap.md`` Sprint 6 — starting points, not optimized or
    recommended settings. ``rsi_exit_floor`` is the optional RSI exit rule,
    disabled until explicitly set (architecture.md §8).
    """

    product_id: str
    timeframe: str
    fast_ema_period: int = 20
    slow_ema_period: int = 50
    rsi_period: int = 14
    rsi_entry_ceiling: float = 70.0
    rsi_exit_floor: float | None = None

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

        if self.rsi_exit_floor is not None:
            if not _is_number(self.rsi_exit_floor):
                problems.append(
                    "The RSI exit floor must be a number between 0 and 100 (exclusive), "
                    "or left empty to disable it."
                )
            elif not 0 < self.rsi_exit_floor < 100:
                problems.append(
                    "The RSI exit floor must be between 0 and 100 (exclusive), "
                    "or left empty to disable it."
                )

        return problems

    def to_dict(self) -> dict[str, object]:
        from dataclasses import asdict

        return asdict(self)

    def require_valid(self) -> None:
        """Raise :class:`StrategyConfigError` listing every problem, if invalid."""
        problems = self.validate()
        if problems:
            raise StrategyConfigError(" ".join(problems))

    def config_hash(self) -> str:
        """Stable SHA-256 identity of this configuration's decision-relevant fields."""
        canonical = json.dumps(
            {
                "name": STRATEGY_NAME,
                "fast_ema_period": self.fast_ema_period,
                "slow_ema_period": self.slow_ema_period,
                "rsi_period": self.rsi_period,
                "rsi_entry_ceiling": self.rsi_entry_ceiling,
                "rsi_exit_floor": self.rsi_exit_floor,
                "product_id": self.product_id,
                "timeframe": self.timeframe,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


@dataclass(frozen=True)
class DonchianConfig:
    """Configuration for the Donchian-channel breakout strategy.

    BUY when the close exceeds the highest high of the prior ``entry_lookback``
    candles; SELL when the close falls below the lowest low of the prior
    ``exit_lookback`` candles (turtle-style: the exit channel is shorter than
    the entry channel). The EMA/RSI fields of the baseline do not apply.
    """

    product_id: str
    timeframe: str
    entry_lookback: int = 20
    exit_lookback: int = 10

    MIN_ENTRY = 5
    MAX_ENTRY = 200
    MIN_EXIT = 2
    MAX_EXIT = 100

    def validate(self) -> list[str]:
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
        if not isinstance(self.entry_lookback, int) or isinstance(self.entry_lookback, bool):
            problems.append(
                f"The entry lookback must be a whole number between "
                f"{self.MIN_ENTRY} and {self.MAX_ENTRY}."
            )
        elif not self.MIN_ENTRY <= self.entry_lookback <= self.MAX_ENTRY:
            problems.append(
                f"The entry lookback must be between {self.MIN_ENTRY} and {self.MAX_ENTRY}."
            )
        if not isinstance(self.exit_lookback, int) or isinstance(self.exit_lookback, bool):
            problems.append(
                f"The exit lookback must be a whole number between "
                f"{self.MIN_EXIT} and {self.MAX_EXIT}."
            )
        elif not self.MIN_EXIT <= self.exit_lookback <= self.MAX_EXIT:
            problems.append(
                f"The exit lookback must be between {self.MIN_EXIT} and {self.MAX_EXIT}."
            )
        if (
            isinstance(self.entry_lookback, int)
            and isinstance(self.exit_lookback, int)
            and not isinstance(self.entry_lookback, bool)
            and not isinstance(self.exit_lookback, bool)
            and self.exit_lookback >= self.entry_lookback
        ):
            problems.append(
                "The exit lookback must be shorter than the entry lookback "
                f"(exit: {self.exit_lookback}, entry: {self.entry_lookback})."
            )
        return problems

    def to_dict(self) -> dict[str, object]:
        from dataclasses import asdict

        return asdict(self)

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise StrategyConfigError(" ".join(problems))

    def config_hash(self) -> str:
        """Stable SHA-256 identity of this configuration's decision-relevant fields."""
        canonical = json.dumps(
            {
                "name": DONCHIAN_STRATEGY_NAME,
                "entry_lookback": self.entry_lookback,
                "exit_lookback": self.exit_lookback,
                "product_id": self.product_id,
                "timeframe": self.timeframe,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
