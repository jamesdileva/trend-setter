"""Typed exchange DTOs — the only exchange shapes the rest of the app sees.

Field names mirror the verified Coinbase product/order schema
(``docs/coinbase-verification-checklist.md``) so the future live adapter
maps one-to-one. All amounts are ``Decimal``; all timestamps are UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class AccountBalance:
    """An account currency balance snapshot."""

    currency: str
    available: Decimal
    hold: Decimal


@dataclass(frozen=True)
class ProductInfo:
    """Trading constraints for one product (verified Coinbase field names)."""

    product_id: str
    base_increment: Decimal
    quote_increment: Decimal
    price_increment: Decimal
    base_min_size: Decimal
    base_max_size: Decimal
    quote_min_size: Decimal
    quote_max_size: Decimal
    limit_only: bool
    post_only: bool
    cancel_only: bool
    trading_disabled: bool


@dataclass(frozen=True)
class OrderRequest:
    """An order intent as handed to the adapter by the execution layer.

    Exactly one of ``base_size`` / ``quote_size`` is set, depending on the
    order configuration. ``client_order_id`` is the durable idempotency
    identity created before submission (architecture.md §10).
    """

    client_order_id: str
    product_id: str
    side: OrderSide
    base_size: Decimal | None = None
    quote_size: Decimal | None = None
    limit_price: Decimal | None = None


@dataclass(frozen=True)
class OrderResult:
    """The immediate outcome of a submission attempt.

    ``accepted`` means the exchange acknowledged creation. An unknown
    outcome (timeout after submission) is represented by the execution
    layer, not by fabricating a result here.
    """

    client_order_id: str
    exchange_order_id: str | None
    accepted: bool
    failure_reason: str | None = None


@dataclass(frozen=True)
class OrderSnapshot:
    """Current known state of one exchange order."""

    exchange_order_id: str
    client_order_id: str
    product_id: str
    side: OrderSide
    status: str
    filled_size: Decimal
    total_fees: Decimal


@dataclass(frozen=True)
class Fill:
    """One confirmed execution. Fills are the source of truth for positions."""

    exchange_order_id: str
    trade_id: str
    product_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    commission: Decimal
    trade_time: datetime
