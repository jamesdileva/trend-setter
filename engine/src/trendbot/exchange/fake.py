"""Deterministic fake adapter for tests and paper plumbing.

No network, no credentials, no real orders — ever. Behavior mirrors the
verified Coinbase semantics where it matters, most notably: a duplicate
``client_order_id`` returns the existing order instead of creating a new
one (``docs/coinbase-verification-checklist.md``, item 6).

Testing extensions:

- ``simulate_unknown_outcome``: the next submission for that id is
  accepted internally but raises :class:`UnknownOutcomeError` — exactly
  the "request accepted, response lost" scenario the submission flow and
  reconciler must survive.
- ``simulate_partial_fill`` / ``simulate_full_fill``: drive fill events
  (including cancel/fill races) through ``list_fills``.

Fixture values below are test fixtures, not verified market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trendbot.exchange.base import ExchangeAdapter, UnknownOutcomeError
from trendbot.exchange.types import (
    AccountBalance,
    Fill,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderSnapshot,
    ProductInfo,
)
from trendbot.market_data.candles import Candle

PRODUCTS: dict[str, ProductInfo] = {
    "BTC-USD": ProductInfo(
        product_id="BTC-USD",
        base_increment=Decimal("0.00000001"),
        quote_increment=Decimal("0.01"),
        price_increment=Decimal("0.01"),
        base_min_size=Decimal("0.0001"),
        base_max_size=Decimal("1000"),
        quote_min_size=Decimal("1.00"),
        quote_max_size=Decimal("1000000.00"),
        limit_only=False,
        post_only=False,
        cancel_only=False,
        trading_disabled=False,
    ),
    "ETH-USD": ProductInfo(
        product_id="ETH-USD",
        base_increment=Decimal("0.00000001"),
        quote_increment=Decimal("0.01"),
        price_increment=Decimal("0.01"),
        base_min_size=Decimal("0.001"),
        base_max_size=Decimal("10000"),
        quote_min_size=Decimal("1.00"),
        quote_max_size=Decimal("1000000.00"),
        limit_only=False,
        post_only=False,
        cancel_only=False,
        trading_disabled=False,
    ),
}

_START_PRICE = {"BTC-USD": Decimal("65000.00"), "ETH-USD": Decimal("3100.00")}


def supported_products() -> list[str]:
    return sorted(PRODUCTS)


class FakeExchangeAdapter(ExchangeAdapter):
    """In-memory adapter with deterministic fixture data."""

    def __init__(self, starting_balance: Decimal = Decimal("10000.00")) -> None:
        self._accounts = [
            AccountBalance(currency="USD", available=starting_balance, hold=Decimal("0")),
            AccountBalance(currency="BTC", available=Decimal("0.5"), hold=Decimal("0")),
            AccountBalance(currency="ETH", available=Decimal("2.5"), hold=Decimal("0")),
        ]
        self._orders_by_client_id: dict[str, OrderSnapshot] = {}
        self._orders_by_exchange_id: dict[str, OrderSnapshot] = {}
        self._canceled: set[str] = set()
        self._fills: list[Fill] = []
        self._unknown_outcome_ids: set[str] = set()
        self._order_sizes: dict[str, Decimal] = {}
        self._counter = 0
        self.create_calls = 0

    # -- market data -------------------------------------------------

    def test_connection(self) -> bool:
        return True

    def get_accounts(self) -> list[AccountBalance]:
        return list(self._accounts)

    def get_product(self, product_id: str) -> ProductInfo:
        try:
            return PRODUCTS[product_id]
        except KeyError:
            raise KeyError(
                f"Product {product_id!r} is not supported by the fake adapter. "
                f"Supported products: {', '.join(supported_products())}."
            ) from None

    def get_historical_candles(
        self, product_id: str, granularity: str, start: datetime, end: datetime
    ) -> list[Candle]:
        if product_id not in PRODUCTS:
            raise KeyError(
                f"Product {product_id!r} is not supported by the fake adapter. "
                f"Supported products: {', '.join(supported_products())}."
            )
        step = timedelta(hours=1) if granularity in ("ONE_HOUR", "1h") else timedelta(minutes=1)
        candles: list[Candle] = []
        price = _START_PRICE[product_id]
        current = start
        while current < end:
            price = price + Decimal("10")
            candle = Candle(
                product_id=product_id,
                granularity=granularity,
                start_time=current,
                open=price,
                high=price + Decimal("5"),
                low=price - Decimal("5"),
                close=price,
                volume=Decimal("1.5"),
            )
            problems = candle.validate()
            if problems:  # pragma: no cover - fixture construction is tested
                raise ValueError(f"Fake adapter generated an invalid candle: {' '.join(problems)}")
            candles.append(candle)
            current += step
        return candles

    # -- orders ------------------------------------------------------

    def create_order(self, request: OrderRequest) -> OrderResult:
        self.create_calls += 1
        if request.product_id not in PRODUCTS:
            return OrderResult(
                client_order_id=request.client_order_id,
                exchange_order_id=None,
                accepted=False,
                failure_reason=(
                    f"Product {request.product_id!r} is not supported. "
                    f"Supported products: {', '.join(supported_products())}."
                ),
            )
        existing = self._orders_by_client_id.get(request.client_order_id)
        if existing is not None:
            # Verified Coinbase behavior: a duplicate id never creates a second order.
            return OrderResult(
                client_order_id=request.client_order_id,
                exchange_order_id=existing.exchange_order_id,
                accepted=True,
            )
        self._counter += 1
        snapshot = OrderSnapshot(
            exchange_order_id=f"fake-{self._counter:06d}",
            client_order_id=request.client_order_id,
            product_id=request.product_id,
            side=request.side,
            status="OPEN",
            filled_size=Decimal("0"),
            total_fees=Decimal("0"),
        )
        self._orders_by_client_id[request.client_order_id] = snapshot
        self._orders_by_exchange_id[snapshot.exchange_order_id] = snapshot
        self._order_sizes[request.client_order_id] = request.base_size or Decimal(0)
        if request.client_order_id in self._unknown_outcome_ids:
            # First attempt: accepted internally, response "lost". A retry
            # with the same id finds the existing order (one-shot loss) —
            # exactly the duplicate-protection behavior of the real API.
            self._unknown_outcome_ids.discard(request.client_order_id)
            raise UnknownOutcomeError(request.client_order_id)
        return OrderResult(
            client_order_id=request.client_order_id,
            exchange_order_id=snapshot.exchange_order_id,
            accepted=True,
        )

    def get_order(self, exchange_order_id: str) -> OrderSnapshot | None:
        return self._orders_by_exchange_id.get(exchange_order_id)

    def list_open_orders(self, product_id: str | None = None) -> list[OrderSnapshot]:
        return [
            order
            for order in self._orders_by_exchange_id.values()
            if order.status == "OPEN"
            and order.exchange_order_id not in self._canceled
            and (product_id is None or order.product_id == product_id)
        ]

    def list_fills(self, product_id: str | None = None) -> list[Fill]:
        if product_id is None:
            return list(self._fills)
        return [fill for fill in self._fills if fill.product_id == product_id]

    def cancel_order(self, exchange_order_id: str) -> bool:
        if exchange_order_id not in self._orders_by_exchange_id:
            return False
        self._canceled.add(exchange_order_id)
        return True

    # -- test simulation hooks ---------------------------------------

    def simulate_unknown_outcome(self, client_order_id: str) -> None:
        """The next create_order for this id is accepted but its response is lost."""
        self._unknown_outcome_ids.add(client_order_id)

    def simulate_fill(
        self,
        client_order_id: str,
        price: Decimal,
        size: Decimal | None = None,
        *,
        when: datetime | None = None,
    ) -> Fill | None:
        """Record a fill for an existing simulated order (partial or full).

        With ``size`` given the order becomes PARTIALLY_FILLED (unless the
        cumulative size reaches the ordered size); without it the order
        fills completely.
        """
        snapshot = self._orders_by_client_id.get(client_order_id)
        if snapshot is None:
            return None
        ordered = self._order_sizes.get(client_order_id, snapshot.filled_size + Decimal(1))
        fill_size = size if size is not None else ordered - snapshot.filled_size
        fill = Fill(
            exchange_order_id=snapshot.exchange_order_id,
            trade_id=f"trade-{len(self._fills) + 1}",
            product_id=snapshot.product_id,
            side=OrderSide(snapshot.side),
            price=price,
            size=fill_size,
            commission=price * fill_size * Decimal("0.01"),
            trade_time=when or datetime.now(UTC),
        )
        self._fills.append(fill)
        new_filled = snapshot.filled_size + fill_size
        status = "FILLED" if new_filled >= ordered else "PARTIALLY_FILLED"
        updated = replace(
            snapshot,
            status=status,
            filled_size=new_filled,
            total_fees=snapshot.total_fees + fill.commission,
        )
        self._orders_by_client_id[client_order_id] = updated
        self._orders_by_exchange_id[snapshot.exchange_order_id] = updated
        return fill
