"""Reconciliation: exchange state wins after restarts and reconnects
(architecture.md §6, roadmap Sprint 8 task 10).

Unresolved intents are re-checked against the exchange:

- known exchange order id → query its status and adopt it (open/filled/
  canceled);
- ``unknown_submission`` with no id → **duplicate probe**: resubmit with
  the same client order id. Verified Coinbase semantics return the
  existing order without creating a second one, so the probe is safe and
  can never duplicate the order.

Intents that cannot be resolved stay in a safe paused state and are
reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trendbot.database.models import OrderIntent
from trendbot.database.repositories import (
    ExchangeOrderRepository,
    OrderIntentRepository,
)
from trendbot.database.session import Database
from trendbot.exchange.base import ExchangeAdapter, UnknownOutcomeError
from trendbot.exchange.types import OrderRequest, OrderSide
from trendbot.execution.state_machine import (
    ACKNOWLEDGED,
    CANCEL_PENDING,
    CANCELED,
    CREATED,
    FILLED,
    OPEN,
    PARTIALLY_FILLED,
    RECONCILIATION_REQUIRED,
    RISK_APPROVED,
    SUBMITTING,
    UNKNOWN_SUBMISSION,
)


@dataclass
class ReconciliationReport:
    checked: int = 0
    resolved_open: int = 0
    resolved_filled: int = 0
    resolved_canceled: int = 0
    still_unresolved: int = 0
    details: list[str] = field(default_factory=list)


_STATUS_TO_STATE = {
    "OPEN": OPEN,
    "PENDING": ACKNOWLEDGED,
    "FILLED": FILLED,
    "CANCELLED": CANCELED,
    "CANCELED": CANCELED,
    "EXPIRED": CANCELED,
    "FAILED": CANCELED,
    "QUEUED": ACKNOWLEDGED,
}

# States that are already consistent with the exchange view.
NO_RECONCILIATION_NEEDED = frozenset(
    {OPEN, PARTIALLY_FILLED, CREATED, RISK_APPROVED, CANCEL_PENDING}
)


class Reconciler:
    """Brings local order intents back in line with exchange truth."""

    def __init__(self, database: Database, adapter: ExchangeAdapter) -> None:
        self._intents = OrderIntentRepository(database)
        self._exchange_orders = ExchangeOrderRepository(database)
        self._adapter = adapter

    def reconcile_pending(self) -> ReconciliationReport:
        report = ReconciliationReport()
        for intent in self._intents.list_unresolved():
            report.checked += 1
            if intent.state in NO_RECONCILIATION_NEEDED:
                continue

            exchange_id = self._exchange_orders.exchange_id_for(intent.client_order_id)
            snapshot = self._adapter.get_order(exchange_id) if exchange_id else None

            if snapshot is not None:
                new_state = _STATUS_TO_STATE.get(snapshot.status)
                if new_state is not None:
                    self._intents.mark(intent.client_order_id, new_state)
                    self._exchange_orders.record(
                        client_order_id=intent.client_order_id,
                        exchange_order_id=snapshot.exchange_order_id,
                        product_id=intent.product_id,
                        side=OrderSide(intent.side),
                        status=snapshot.status,
                    )
                    self._count(report, new_state)
                    report.details.append(
                        f"{intent.client_order_id}: exchange says {snapshot.status}."
                    )
                    continue

            if intent.state in (SUBMITTING, UNKNOWN_SUBMISSION):
                # Lost before any acknowledgment: needs the duplicate probe.
                self._intents.mark(intent.client_order_id, RECONCILIATION_REQUIRED)
                refreshed = self._intents.get(intent.client_order_id)
                assert refreshed is not None
                intent = refreshed

            if intent.state in (RECONCILIATION_REQUIRED, UNKNOWN_SUBMISSION):
                resolved = self._probe_duplicate(intent.client_order_id, intent)
                if resolved is not None:
                    self._count(report, resolved)
                    report.details.append(
                        f"{intent.client_order_id}: duplicate probe resolved → {resolved}."
                    )
                    continue
            report.still_unresolved += 1
            report.details.append(
                f"{intent.client_order_id}: unresolved ({intent.state}) — left safe-paused."
            )
        return report

    def _probe_duplicate(
        self, client_order_id: str, intent: OrderIntent
    ) -> str | None:
        """Re-submit with the SAME client order id (never duplicates).

        Verified Coinbase behavior: an existing id returns the existing
        order instead of creating a new one. A genuinely-lost order is
        created here — same id, same logical order.
        """
        try:
            result = self._adapter.create_order(
                OrderRequest(
                    client_order_id=client_order_id,
                    product_id=intent.product_id,
                    side=OrderSide(intent.side),
                    base_size=intent.base_size,
                    limit_price=intent.limit_price,
                )
            )
        except UnknownOutcomeError:
            return None
        if not result.accepted or result.exchange_order_id is None:
            self._intents.mark(intent.client_order_id, CANCELED)
            return CANCELED
        self._exchange_orders.record(
            client_order_id=client_order_id,
            exchange_order_id=result.exchange_order_id,
            product_id=intent.product_id,
            side=intent.side,
            status="OPEN",
        )
        snapshot = self._adapter.get_order(result.exchange_order_id)
        new_state = (
            _STATUS_TO_STATE.get(snapshot.status, OPEN) if snapshot is not None else OPEN
        )
        self._intents.mark(client_order_id, new_state)
        return new_state

    @staticmethod
    def _count(report: ReconciliationReport, state: str) -> None:
        if state == OPEN:
            report.resolved_open += 1
        elif state == FILLED:
            report.resolved_filled += 1
        elif state == CANCELED:
            report.resolved_canceled += 1
