"""Configurable risk limits (architecture.md §9).

Defaults are deliberately conservative starting points — not validated
recommendations. A percentage-risk setting never guarantees a maximum
loss: gaps, slippage, fees, and outages can exceed estimates.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DEFAULT_MAX_ORDER_QUOTE = Decimal("500")
DEFAULT_MAX_POSITION_QUOTE = Decimal("1000")
DEFAULT_MAX_TOTAL_EXPOSURE_QUOTE = Decimal("2000")
DEFAULT_MAX_OPEN_ORDERS = 3
DEFAULT_MAX_OPEN_POSITIONS = 2
DEFAULT_DAILY_DRAWDOWN_LIMIT_PCT = Decimal("3.0")
DEFAULT_MIN_BASE_SIZE = Decimal("0.0001")
DEFAULT_MAX_BASE_SIZE = Decimal("1000")


@dataclass(frozen=True)
class RiskLimits:
    """Conservative default limits; every value is validated per order."""

    max_order_quote: Decimal = DEFAULT_MAX_ORDER_QUOTE
    max_position_quote: Decimal = DEFAULT_MAX_POSITION_QUOTE
    max_total_exposure_quote: Decimal = DEFAULT_MAX_TOTAL_EXPOSURE_QUOTE
    max_open_orders: int = DEFAULT_MAX_OPEN_ORDERS
    max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS
    daily_drawdown_limit_pct: Decimal = DEFAULT_DAILY_DRAWDOWN_LIMIT_PCT
    min_base_size: Decimal = DEFAULT_MIN_BASE_SIZE
    max_base_size: Decimal = DEFAULT_MAX_BASE_SIZE
