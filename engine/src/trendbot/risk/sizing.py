"""Position sizing with decimal arithmetic (architecture.md §9).

Quote notional converts to base size at the expected price, rounded
**down** to the product increment; sizes below the product minimum or
above its maximum are rejected. Binary floats never touch sizing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from trendbot.exchange.types import ProductInfo
from trendbot.strategies.config import StrategyConfigError


@dataclass(frozen=True)
class SizedOrder:
    base_size: Decimal
    quote_notional: Decimal
    price: Decimal


def size_entry(
    quote_notional: Decimal,
    price: Decimal,
    product: ProductInfo,
) -> SizedOrder:
    """Size one entry: quote / price floored to the product increment.

    Raises :class:`StrategyConfigError` with plain-language reasons when
    the price is invalid or the resulting size violates product bounds.
    """
    if price <= 0:
        raise StrategyConfigError("The entry price must be positive to size an order.")
    if quote_notional <= 0:
        raise StrategyConfigError("The order value must be positive.")
    raw = quote_notional / price
    increment = product.base_increment
    if increment <= 0:
        raise StrategyConfigError("The product increment must be positive.")
    steps = (raw / increment).to_integral_value(rounding=ROUND_FLOOR)
    base_size = steps * increment
    if base_size < product.base_min_size:
        raise StrategyConfigError(
            f"The order size ({base_size}) is below the product minimum "
            f"({product.base_min_size}). Increase the order value."
        )
    if base_size > product.base_max_size:
        raise StrategyConfigError(
            f"The order size ({base_size}) exceeds the product maximum "
            f"({product.base_max_size})."
        )
    return SizedOrder(base_size=base_size, quote_notional=quote_notional, price=price)
