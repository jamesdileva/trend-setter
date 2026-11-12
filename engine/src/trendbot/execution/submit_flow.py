"""The safe submission sequence (architecture.md §10; roadmap Sprint 8).

Order of operations, no exceptions:

1. size the order (decimal, increments);
2. run the risk gate — a rejection persists a durable intent in state
   ``rejected`` and the adapter is never touched;
3. persist the intent (``created`` → ``risk_approved``) **before** any
   network call;
4. mark ``submitting``, submit via the adapter;
5. acknowledged → exchange id recorded → ``open``;
6. timeout/unknown outcome → ``unknown_submission`` → **no blind retry** →
   reconciliation_required → the reconciler resolves using the verified
   duplicate-protection semantics.

Failure streaks persist so a cooldown can gate subsequent entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trendbot.database.repositories import (
    ExchangeOrderRepository,
    OrderIntentRepository,
    PositionRepository,
    RiskRepository,
    SettingsRepository,
)
from trendbot.database.session import Database
from trendbot.exchange.base import ExchangeAdapter, UnknownOutcomeError
from trendbot.exchange.types import OrderRequest, OrderSide
from trendbot.execution.intents import IntentService
from trendbot.execution.reconcile import Reconciler
from trendbot.execution.state_machine import OPEN, SUBMITTING, UNKNOWN_SUBMISSION
from trendbot.risk.daily import DailyLedger
from trendbot.risk.manager import RiskContext, RiskDecision, RiskManager
from trendbot.risk.sizing import size_entry

COOLDOWN_FAILURE_STREAK = 3
COOLDOWN_SECONDS = 300.0


@dataclass(frozen=True)
class SubmissionOutcome:
    status: str  # submitted | rejected | reconciled
    client_order_id: str
    exchange_order_id: str | None
    risk: RiskDecision
    detail: str


def update_failure_streak(
    database: Database, *, ok: bool, now: datetime | None = None
) -> tuple[int, datetime | None]:
    """Persist the consecutive-failure streak for the cooldown gate."""
    settings = SettingsRepository(database)
    moment = now or datetime.now(UTC)
    streak = int(settings.get("consecutive_failures", "0") or 0)
    last_raw = settings.get("last_failure_at")
    last = datetime.fromisoformat(last_raw) if last_raw else None
    if ok:
        streak = 0
        settings.set("consecutive_failures", "0")
        return streak, last
    streak += 1
    settings.set("consecutive_failures", str(streak))
    settings.set("last_failure_at", moment.isoformat())
    return streak, moment


def cooldown_active(database: Database, *, now: datetime | None = None) -> bool:
    """True within the cooldown window after COOLDOWN_FAILURE_STREAK failures."""
    settings = SettingsRepository(database)
    streak = int(settings.get("consecutive_failures", "0") or 0)
    if streak < COOLDOWN_FAILURE_STREAK:
        return False
    last_raw = settings.get("last_failure_at")
    if not last_raw:
        return False
    last = datetime.fromisoformat(last_raw)
    moment = now or datetime.now(UTC)
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (moment - last).total_seconds() <= COOLDOWN_SECONDS


class OrderSubmissionFlow:
    """Submits risk-approved, durably-persisted order intents."""

    def __init__(
        self,
        database: Database,
        adapter: ExchangeAdapter,
        risk_manager: RiskManager | None = None,
    ) -> None:
        self._db = database
        self._adapter = adapter
        self._risk = risk_manager or RiskManager()
        self._intents = IntentService(database)
        self._intent_repo = OrderIntentRepository(database)
        self._risk_events = RiskRepository(database)
        self._ledger = DailyLedger(database)

    def submit_entry(
        self,
        *,
        product_id: str,
        quote_notional: Decimal,
        price: Decimal,
        bucket_key: str,
        config_hash: str,
        cash_available: Decimal,
        stale_data: bool = False,
        kill_switch_active: bool | None = None,
        now: datetime | None = None,
    ) -> SubmissionOutcome:
        """Gate, persist, and submit one entry intent (side=buy)."""
        moment = now or datetime.now(UTC)
        product = self._adapter.get_product(product_id)
        sized = size_entry(quote_notional, price, product)
        client_order_id = None

        try:
            intent, created = self._intents.get_or_create_entry(
                product_id=product_id,
                side="buy",
                bucket_key=bucket_key,
                config_hash=config_hash,
                base_size=sized.base_size,
                price=price,
            )
            client_order_id = intent.client_order_id
            if not created:
                return SubmissionOutcome(
                    status="duplicate",
                    client_order_id=client_order_id,
                    exchange_order_id=None,
                    risk=RiskDecision(
                        False,
                        "duplicate_intent",
                        "An intent for this signal already exists.",
                    ),
                    detail="The same signal bucket already has a durable intent.",
                )

            positions = PositionRepository(database=self._db)
            position = positions.get(product_id)
            current_position_quote = (
                (position.size or Decimal(0)) * price if position else Decimal(0)
            )
            total_exposure = sum(
                ((p.size or Decimal(0)) * price for p in positions.open_positions()),
                start=Decimal(0),
            )
            kill_switch = (
                kill_switch_active
                if kill_switch_active is not None
                else (SettingsRepository(self._db).get("kill_switch_active") == "true")
            )
            drawdown = self._ledger.drawdown_pct(
                cash_available + total_exposure, now=moment
            )
            context = RiskContext(
                product_id=product_id,
                quote_notional=quote_notional,
                base_size=sized.base_size,
                price=price,
                product=product,
                current_position_quote=current_position_quote,
                total_exposure_quote=total_exposure,
                open_orders_count=len(
                    [
                        row
                        for row in self._intent_repo.list_unresolved()
                        if row.state in ("open", "acknowledged", "partially_filled")
                    ]
                ),
                open_positions_count=len(positions.open_positions()),
                cash_available=cash_available,
                daily_drawdown_pct=drawdown,
                stale_data=stale_data,
                cooldown_active=cooldown_active(self._db, now=moment),
                kill_switch_active=kill_switch,
            )
            decision = self._risk.check_entry(context)
            if not decision.allowed:
                self._intent_repo.mark(
                    intent.client_order_id, "rejected", risk_reason=decision.message
                )
                self._risk_events.record(
                    event_kind="order_rejected",
                    product_id=product_id,
                    detail={"reason_code": decision.reason_code, "message": decision.message},
                )
                update_failure_streak(self._db, ok=False, now=moment)
                return SubmissionOutcome(
                    status="rejected",
                    client_order_id=intent.client_order_id,
                    exchange_order_id=None,
                    risk=decision,
                    detail=decision.message,
                )

            self._intent_repo.mark(intent.client_order_id, "risk_approved")
            self._intent_repo.mark(intent.client_order_id, SUBMITTING)
            try:
                result = self._adapter.create_order(
                    OrderRequest(
                        client_order_id=intent.client_order_id,
                        product_id=product_id,
                        side=OrderSide.BUY,
                        base_size=sized.base_size,
                        limit_price=price,
                    )
                )
            except UnknownOutcomeError:
                self._intent_repo.mark(intent.client_order_id, UNKNOWN_SUBMISSION)
                self._intent_repo.mark(intent.client_order_id, "reconciliation_required")
                self._risk_events.record(
                    event_kind="submission_unknown_outcome",
                    product_id=product_id,
                    detail={"client_order_id": intent.client_order_id},
                )
                update_failure_streak(self._db, ok=False, now=moment)
                report = Reconciler(self._db, self._adapter).reconcile_pending()
                row = self._intent_repo.get(intent.client_order_id)
                assert row is not None
                return SubmissionOutcome(
                    status="reconciled",
                    client_order_id=intent.client_order_id,
                    exchange_order_id=None,
                    risk=decision,
                    detail=f"Unknown outcome reconciled: {row.state}; {report.details}",
                )
            if not result.accepted or result.exchange_order_id is None:
                self._intent_repo.mark(intent.client_order_id, "rejected")
                self._risk_events.record(
                    event_kind="exchange_rejected",
                    product_id=product_id,
                    detail={"reason": result.failure_reason},
                )
                update_failure_streak(self._db, ok=False, now=moment)
                return SubmissionOutcome(
                    status="rejected",
                    client_order_id=intent.client_order_id,
                    exchange_order_id=None,
                    risk=decision,
                    detail=result.failure_reason or "The exchange rejected the order.",
                )

            self._intent_repo.mark(intent.client_order_id, "acknowledged")
            self._exchange_orders_for_flow().record(
                client_order_id=intent.client_order_id,
                exchange_order_id=result.exchange_order_id,
                product_id=product_id,
                side="buy",
                status="OPEN",
            )
            snapshot = self._adapter.get_order(result.exchange_order_id)
            if snapshot is not None and snapshot.status == "OPEN":
                self._intent_repo.mark(intent.client_order_id, OPEN)
            update_failure_streak(self._db, ok=True, now=moment)
            return SubmissionOutcome(
                status="submitted",
                client_order_id=intent.client_order_id,
                exchange_order_id=result.exchange_order_id,
                risk=decision,
                detail="Order submitted and open.",
            )
        except Exception as exc:  # noqa: BLE001 - the pipeline must fail safe
            if client_order_id is not None:
                try:
                    self._intent_repo.mark(client_order_id, "reconciliation_required")
                except Exception:  # noqa: BLE001 - durable state best effort
                    pass
            self._risk_events.record(
                event_kind="submission_error",
                product_id=product_id,
                detail={"error": str(exc)},
            )
            return SubmissionOutcome(
                status="error",
                client_order_id=client_order_id or "",
                exchange_order_id=None,
                risk=RiskDecision(False, "submission_error", str(exc)),
                detail=str(exc),
            )

    def _exchange_orders_for_flow(self) -> ExchangeOrderRepository:
        return self._intents.exchange_orders()


def daily_drawdown_for(
    database: Database, equity: Decimal, *, now: datetime | None = None
) -> Decimal:
    """Convenience: current drawdown percent for the UTC day."""
    return DailyLedger(database).drawdown_pct(equity, now=now)


def cooldown_window_expired(last_failure_at: datetime, *, now: datetime) -> bool:
    return (now - last_failure_at) > timedelta(seconds=COOLDOWN_SECONDS)
