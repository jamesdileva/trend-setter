"""Durable order intents with deterministic client order identity (Sprint 8).

Client order IDs are deterministic UUIDs over (product, side, signal
bucket, config hash): the same signal bucket never produces two intents,
and re-probing the exchange with the same id can never create a second
order (verified Coinbase duplicate protection, checklist item 6).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from trendbot.database.models import OrderIntent
from trendbot.database.repositories import ExchangeOrderRepository, OrderIntentRepository
from trendbot.database.session import Database

# Stable namespace for this application's client order IDs.
CLIENT_ORDER_NAMESPACE = uuid.UUID("5f3a9c1e-7b2d-4c6a-9d8e-1a2b3c4d5e6f")


def client_order_id_for(
    product_id: str, side: str, bucket_key: str, config_hash: str
) -> str:
    """Deterministic id: identical inputs yield the identical id."""
    name = f"trendbot:{product_id}:{side}:{bucket_key}:{config_hash}"
    return str(uuid.uuid5(CLIENT_ORDER_NAMESPACE, name))


class IntentService:
    """Creates and tracks durable order intents."""

    def __init__(self, database: Database) -> None:
        self._intents = OrderIntentRepository(database)
        self._exchange_orders = ExchangeOrderRepository(database)

    def get_or_create_entry(
        self,
        *,
        product_id: str,
        side: str,
        bucket_key: str,
        config_hash: str,
        base_size: Decimal,
        price: Decimal,
        order_kind: str = "limit",
    ) -> tuple[OrderIntent, bool]:
        """Fetch or create the intent for one signal bucket.

        Returns (intent, created). The intent is persisted with state
        ``created`` before any risk decision or network call.
        """
        client_order_id = client_order_id_for(product_id, side, bucket_key, config_hash)
        existing = self._intents.get(client_order_id)
        if existing is not None:
            return existing, False
        row = self._intents.create(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            order_kind=order_kind,
            base_size=base_size,
            limit_price=price,
        )
        assert row is not None  # just checked for existence
        return row, True

    def intents(self) -> OrderIntentRepository:
        return self._intents

    def exchange_orders(self) -> ExchangeOrderRepository:
        return self._exchange_orders
