"""Core candle domain type (architecture.md §7).

Prices and volumes are ``Decimal`` — binary floats are never used for
market data that feeds sizing or accounting. Validation rules come from
architecture.md §7 (candle correctness).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    """A single OHLCV candle. ``start_time`` is the UTC bucket start."""

    product_id: str
    granularity: str
    start_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_complete: bool = True

    def validate(self) -> list[str]:
        """Return plain-language problems; an empty list means valid."""
        problems: list[str] = []
        if self.high < max(self.open, self.close):
            problems.append("The candle high must be at least the greater of open and close.")
        if self.low > min(self.open, self.close):
            problems.append("The candle low must be at most the lesser of open and close.")
        if self.volume < 0:
            problems.append("The candle volume must be nonnegative.")
        return problems
