"""Exchange adapter contract (architecture.md §6, implementation.md §6).

Everything exchange-specific lives behind this interface: the fake adapter
serves tests and paper plumbing; the Coinbase adapter arrives in the
market-data (Sprint 4) and live-execution (Sprint 10) sprints. Streaming
methods are added with the market-data sprint once the exact WebSocket
contract is implemented.

Rules every adapter must follow (implementation.md §6):

- Normalize errors into typed internal exceptions; never leak raw payloads.
- Use Decimal for amounts; use UTC timestamps.
- Never retry ambiguous order creation without querying exchange state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from trendbot.exchange.types import (
    AccountBalance,
    Fill,
    OrderRequest,
    OrderResult,
    OrderSnapshot,
    ProductInfo,
)
from trendbot.market_data.candles import Candle


class ExchangeAdapter(ABC):
    """Interface every exchange adapter implements."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Validate access with a non-trading request."""

    @abstractmethod
    def get_accounts(self) -> list[AccountBalance]:
        """Return current account balances."""

    @abstractmethod
    def get_product(self, product_id: str) -> ProductInfo:
        """Return trading constraints for one product."""

    @abstractmethod
    def get_historical_candles(
        self, product_id: str, granularity: str, start: datetime, end: datetime
    ) -> list[Candle]:
        """Return validated historical candles for the UTC window [start, end)."""

    @abstractmethod
    def create_order(self, request: OrderRequest) -> OrderResult:
        """Submit one order intent.

        Implementations must honor duplicate ``client_order_id`` semantics:
        a repeated id must never create a second order.
        """

    @abstractmethod
    def get_order(self, exchange_order_id: str) -> OrderSnapshot | None:
        """Return the current state of one exchange order, if known."""

    @abstractmethod
    def list_open_orders(self, product_id: str | None = None) -> list[OrderSnapshot]:
        """Return currently open orders, optionally filtered by product."""

    @abstractmethod
    def list_fills(self, product_id: str | None = None) -> list[Fill]:
        """Return confirmed fills (source of truth for positions)."""

    @abstractmethod
    def cancel_order(self, exchange_order_id: str) -> bool:
        """Request cancellation; return False when the order is unknown."""
