"""Simulation assumptions (architecture.md §11).

Fee and slippage defaults are deliberately conservative **placeholders**:
real Coinbase fee tiers are account-dependent and may change (architecture
§10 forbids hardcoding example rates as facts). Every run records its
assumptions so results are never mistaken for exchange-accurate fills.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_FLOOR, Decimal

# Deliberately conservative placeholder assumptions (not exchange facts).
DEFAULT_FEE_BPS = 100  # 1% per side
DEFAULT_SLIPPAGE_BPS = 10  # 0.1% per side, against the position direction
DEFAULT_BASE_INCREMENT = Decimal("0.00000001")


@dataclass(frozen=True)
class FeeAssumptions:
    """Per-side fee/slippage assumptions and the size rounding increment."""

    fee_bps: float = DEFAULT_FEE_BPS
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    base_increment: Decimal = DEFAULT_BASE_INCREMENT

    @property
    def fee_rate(self) -> Decimal:
        return Decimal(str(self.fee_bps)) / Decimal(10000)

    @property
    def slippage_rate(self) -> Decimal:
        return Decimal(str(self.slippage_bps)) / Decimal(10000)

    def entry_fill(self, open_price: Decimal) -> Decimal:
        """Buy fills pay the ask side of the assumed slippage."""
        return open_price * (Decimal(1) + self.slippage_rate)

    def exit_fill(self, open_price: Decimal) -> Decimal:
        """Sell fills receive the bid side of the assumed slippage."""
        return open_price * (Decimal(1) - self.slippage_rate)

    def round_base_down(self, size: Decimal) -> Decimal:
        """Round a base size down to the product increment (architecture.md §9)."""
        increment = self.base_increment
        if increment <= 0:
            return size
        steps = (size / increment).to_integral_value(rounding=ROUND_FLOOR)
        return steps * increment

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["base_increment"] = str(self.base_increment)
        return data
