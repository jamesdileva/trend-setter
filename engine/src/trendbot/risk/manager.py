"""The risk manager: the mandatory gate (architecture.md §9).

`check` is a pure decision over the provided context — no I/O, fully
deterministic, trivially testable. Callers gather context (positions,
exposure, drawdown, market-data freshness) and persist the decision.
Order of checks is fixed: kill switch → stale data → cooldown → caps →
size bounds → affordability.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trendbot.exchange.types import ProductInfo
from trendbot.risk.limits import RiskLimits


@dataclass(frozen=True)
class RiskContext:
    """Everything the risk manager needs to judge one entry intent."""

    product_id: str
    quote_notional: Decimal
    base_size: Decimal
    price: Decimal
    product: ProductInfo
    current_position_quote: Decimal
    total_exposure_quote: Decimal
    open_orders_count: int
    open_positions_count: int
    cash_available: Decimal
    daily_drawdown_pct: Decimal
    stale_data: bool
    cooldown_active: bool
    kill_switch_active: bool


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason_code: str | None
    message: str


ALLOWED = RiskDecision(allowed=True, reason_code=None, message="Risk checks passed.")


class RiskManager:
    """Pure risk gate. Decisions are persisted by the caller."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def check_entry(self, context: RiskContext) -> RiskDecision:
        limits = self.limits
        if context.kill_switch_active:
            return RiskDecision(
                False,
                "kill_switch_active",
                "Trading is halted by the kill switch. Review the reason and "
                "re-arm before entries resume.",
            )
        if context.stale_data:
            return RiskDecision(
                False,
                "stale_data",
                "Market data is stale or incomplete. New entries are paused.",
            )
        if context.daily_drawdown_pct >= limits.daily_drawdown_limit_pct:
            return RiskDecision(
                False,
                "daily_drawdown_exceeded",
                f"Today's drawdown ({context.daily_drawdown_pct:.2f}%) reached the limit "
                f"({limits.daily_drawdown_limit_pct:.2f}%). New entries are paused until tomorrow.",
            )
        if context.cooldown_active:
            return RiskDecision(
                False,
                "cooldown_active",
                "A cooldown is active after recent losses or order failures. "
                "Entries resume shortly.",
            )
        if context.quote_notional > limits.max_order_quote:
            return RiskDecision(
                False,
                "order_cap_exceeded",
                f"The order value ({context.quote_notional}) exceeds the per-order cap "
                f"({limits.max_order_quote}).",
            )
        if context.base_size < limits.min_base_size:
            return RiskDecision(
                False,
                "below_min_size",
                f"The order size ({context.base_size}) is below the configured minimum "
                f"({limits.min_base_size}).",
            )
        if context.base_size > limits.max_base_size:
            return RiskDecision(
                False,
                "above_max_size",
                f"The order size ({context.base_size}) exceeds the configured maximum "
                f"({limits.max_base_size}).",
            )
        if context.base_size < context.product.base_min_size:
            return RiskDecision(
                False,
                "below_product_min",
                f"The order size ({context.base_size}) is below the product minimum "
                f"({context.product.base_min_size}).",
            )
        if context.product.trading_disabled or context.product.cancel_only:
            return RiskDecision(
                False,
                "product_not_tradable",
                f"{context.product_id} is not currently tradable (disabled or cancel-only).",
            )
        if context.current_position_quote + context.quote_notional > limits.max_position_quote:
            return RiskDecision(
                False,
                "position_cap_exceeded",
                f"The position value after this order "
                f"({context.current_position_quote + context.quote_notional}) would "
                f"exceed the per-position cap ({limits.max_position_quote}).",
            )
        if context.total_exposure_quote + context.quote_notional > limits.max_total_exposure_quote:
            return RiskDecision(
                False,
                "exposure_cap_exceeded",
                f"Total exposure after this order "
                f"({context.total_exposure_quote + context.quote_notional}) would "
                f"exceed the cap ({limits.max_total_exposure_quote}).",
            )
        if context.open_orders_count >= limits.max_open_orders:
            return RiskDecision(
                False,
                "too_many_open_orders",
                f"There are already {context.open_orders_count} open orders "
                f"(limit {limits.max_open_orders}).",
            )
        if (
            context.current_position_quote == 0
            and context.open_positions_count >= limits.max_open_positions
        ):
            return RiskDecision(
                False,
                "too_many_open_positions",
                f"There are already {context.open_positions_count} open positions "
                f"(limit {limits.max_open_positions}).",
            )
        if context.quote_notional > context.cash_available:
            return RiskDecision(
                False,
                "insufficient_cash",
                f"Available cash ({context.cash_available}) cannot cover the order "
                f"({context.quote_notional}).",
            )
        return ALLOWED

    def check_exit(self, context: RiskContext) -> RiskDecision:
        """Exits and protective management continue even when stale or capped.

        Only the kill switch blocks exits: emergency stop means *nothing*
        new goes to the exchange, including exits — cancellation behavior
        is handled by the trading controller instead.
        """
        if context.kill_switch_active:
            return RiskDecision(
                False,
                "kill_switch_active",
                "Trading is halted by the kill switch; exits are managed by the "
                "emergency-stop cancellation flow.",
            )
        return ALLOWED
