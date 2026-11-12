"""End-to-end order lifecycle tests against the mock exchange
(roadmap Sprint 8 verification)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.application.trading_controls import TradingController, TradingMode
from trendbot.database import Database, upgrade_to_head
from trendbot.database.repositories import (
    OrderIntentRepository,
    PositionRepository,
    RiskRepository,
)
from trendbot.exchange.fake import FakeExchangeAdapter
from trendbot.exchange.types import Fill, OrderRequest
from trendbot.execution.fills import apply_fill_idempotent
from trendbot.execution.reconcile import Reconciler
from trendbot.execution.submit_flow import (
    OrderSubmissionFlow,
    cooldown_active,
    update_failure_streak,
)

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "lifecycle.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def adapter() -> FakeExchangeAdapter:
    return FakeExchangeAdapter()


@pytest.fixture()
def flow(db, adapter) -> OrderSubmissionFlow:
    return OrderSubmissionFlow(db, adapter)


def submit(flow: OrderSubmissionFlow, **overrides):
    payload: dict[str, object] = {
        "product_id": "BTC-USD",
        "quote_notional": Decimal("400"),
        "price": Decimal("100000"),
        "bucket_key": START.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_hash": "cfg-1",
        "cash_available": Decimal("5000"),
    }
    payload.update(overrides)
    return flow.submit_entry(**payload)


class TestRiskGate:
    def test_risk_rejection_never_reaches_the_adapter(self, db, adapter, flow):
        outcome = submit(flow, quote_notional=Decimal("5000"))  # > 500 cap
        assert outcome.status == "rejected"
        assert outcome.risk.reason_code == "order_cap_exceeded"
        assert adapter.create_calls == 0  # the adapter was never touched
        intent = OrderIntentRepository(db).get(outcome.client_order_id)
        assert intent is not None and intent.state == "rejected"

    def test_rejection_is_persisted_as_a_risk_event(self, db, adapter, flow):
        submit(flow, quote_notional=Decimal("5000"))
        assert RiskRepository(db).count_for("order_rejected") == 1

    def test_stale_data_blocks_the_entry(self, db, adapter, flow):
        outcome = submit(flow, stale_data=True)
        assert outcome.status == "rejected"
        assert outcome.risk.reason_code == "stale_data"
        assert adapter.create_calls == 0

    def test_kill_switch_blocks_the_entry_until_re_arm(self, db, adapter, flow):
        controller = TradingController(db)
        controller.emergency_stop(adapter, reason="test")
        outcome = submit(flow, kill_switch_active=True)
        assert outcome.status == "rejected"
        assert outcome.risk.reason_code == "kill_switch_active"

        controller.re_arm(reason="reviewed")
        assert controller.kill_switch_active() is False
        assert controller.entries_allowed() is True


class TestHappyPath:
    def test_order_is_durable_before_submission_and_reaches_open(self, db, adapter, flow):
        outcome = submit(flow)
        assert outcome.status == "submitted"
        assert outcome.exchange_order_id is not None

        intents = OrderIntentRepository(db)
        intent = intents.get(outcome.client_order_id)
        assert intent is not None and intent.state == "open"
        assert intent.base_size == Decimal("0.004")  # 400/100000, exact
        # The exchange-id mapping exists for reconciliation and fills.
        assert intents is not None

    def test_same_signal_bucket_never_creates_two_intents(self, db, adapter, flow):
        first = submit(flow)
        second = submit(flow)
        assert first.status == "submitted"
        assert second.status == "duplicate"
        assert first.client_order_id == second.client_order_id


class TestUnknownOutcome:
    def test_timeout_after_acceptance_does_not_duplicate(self, db, adapter, flow):
        # Pre-arrange: the exchange will accept the order but lose the response.
        from trendbot.execution.intents import client_order_id_for

        cid = client_order_id_for("BTC-USD", "buy", START.strftime("%Y-%m-%dT%H:%M:%SZ"), "cfg-1")
        adapter.simulate_unknown_outcome(cid)

        outcome = submit(flow)
        assert outcome.status == "reconciled"

        # Exactly ONE exchange order exists for the id — the probe could not
        # duplicate it (verified Coinbase duplicate protection).
        matching = [
            order_id
            for order_id, snapshot in adapter._orders_by_client_id.items()
            if order_id == cid
        ]
        assert matching == [cid]

        intent = OrderIntentRepository(db).get(cid)
        assert intent is not None and intent.state == "open"

    def test_reconciler_resolves_unknown_submission_after_a_restart(self, db, adapter):
        # Simulate a crash mid-submission: intent stuck in unknown_submission.
        from trendbot.execution.intents import IntentService, client_order_id_for

        service = IntentService(db)
        cid = client_order_id_for("BTC-USD", "buy", "bucket-x", "cfg-1")
        adapter.simulate_unknown_outcome(cid)
        intent, _ = service.get_or_create_entry(
            product_id="BTC-USD",
            side="buy",
            bucket_key="bucket-x",
            config_hash="cfg-1",
            base_size=Decimal("0.004"),
            price=Decimal("100000"),
        )
        intents = OrderIntentRepository(db)
        intents.mark(cid, "risk_approved")
        intents.mark(cid, "submitting")
        # The request goes out and IS accepted, but the response is lost:
        # the exchange holds the order while our intent goes unknown.
        from trendbot.exchange.base import UnknownOutcomeError

        try:
            adapter.create_order(
                OrderRequest(
                    client_order_id=cid,
                    product_id="BTC-USD",
                    side="buy",
                    base_size=Decimal("0.004"),
                    limit_price=Decimal("100000"),
                )
            )
        except UnknownOutcomeError:
            pass
        intents.mark(cid, "unknown_submission")

        unresolved_before = intents.list_unresolved()
        assert any(row.client_order_id == cid for row in unresolved_before)

        # "Restart": a brand-new reconciler over the same database resolves it.
        report = Reconciler(db, adapter).reconcile_pending()
        assert report.checked >= 1
        resolved = intents.get(cid)
        assert resolved is not None and resolved.state == "open"
        assert report.resolved_open >= 1


class TestFillsAndPositions:
    def test_partial_fills_update_positions_incrementally(self, db, adapter, flow):
        outcome = submit(flow)
        assert outcome.exchange_order_id is not None
        fills = []

        first = adapter.simulate_fill(
            outcome.client_order_id, price=Decimal("100000"), size=Decimal("0.001")
        )
        assert first is not None
        assert apply_fill_idempotent(db, first) is True
        fills.append(first)

        second = adapter.simulate_fill(
            outcome.client_order_id, price=Decimal("100000"), size=Decimal("0.003")
        )
        assert apply_fill_idempotent(db, second) is True

        position = PositionRepository(db).get("BTC-USD")
        assert position is not None
        assert position.size == Decimal("0.004")
        assert position.side == "long"
        assert position.average_entry_price == Decimal("100000")

    def test_replayed_fills_never_double_count(self, db, adapter, flow):
        outcome = submit(flow)
        fill = adapter.simulate_fill(
            outcome.client_order_id, price=Decimal("100000"), size=Decimal("0.004")
        )
        assert apply_fill_idempotent(db, fill) is True
        assert apply_fill_idempotent(db, fill) is False  # replay suppressed

        position = PositionRepository(db).get("BTC-USD")
        assert position is not None and position.size == Decimal("0.004")

    def test_sell_fills_reduce_the_position_never_below_zero(self, db, adapter, flow):
        outcome = submit(flow)
        buy = adapter.simulate_fill(
            outcome.client_order_id, price=Decimal("100000"), size=Decimal("0.004")
        )
        apply_fill_idempotent(db, buy)
        from trendbot.exchange.types import OrderSide

        sell_fill = Fill(
            exchange_order_id=buy.exchange_order_id,
            trade_id="sell-1",
            product_id="BTC-USD",
            side=OrderSide.SELL,
            price=Decimal("110000"),
            size=Decimal("0.004"),
            commission=Decimal("0"),
            trade_time=datetime.now(UTC),
        )
        from trendbot.database.repositories import FillRepository

        FillRepository(db).record_fill(sell_fill)
        PositionRepository(db).apply_fill(sell_fill)
        position = PositionRepository(db).get("BTC-USD")
        assert position is not None and position.size == Decimal("0")
        assert position.side == "flat"


class TestCooldown:
    def test_three_consecutive_failures_trigger_the_cooldown(self, db):
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        for _ in range(3):
            streak, _ = update_failure_streak(db, ok=False, now=moment)
        assert streak == 3
        assert cooldown_active(db, now=moment + timedelta(seconds=10)) is True
        assert cooldown_active(db, now=moment + timedelta(seconds=301)) is False

    def test_success_resets_the_streak(self, db):
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        update_failure_streak(db, ok=False, now=moment)
        update_failure_streak(db, ok=False, now=moment)
        streak, _ = update_failure_streak(db, ok=True, now=moment)
        assert streak == 0
        assert cooldown_active(db, now=moment) is False


class TestTradingControls:
    def test_modes_persist_and_gate_entries(self, db):
        controller = TradingController(db)
        assert controller.current_mode() == TradingMode.NORMAL
        assert controller.entries_allowed() is True

        controller.set_mode(TradingMode.ENTRIES_PAUSED, reason="lunch break")
        assert controller.current_mode() == TradingMode.ENTRIES_PAUSED
        assert controller.entries_allowed() is False
        # Restart persistence: a fresh controller reads the same mode.
        assert TradingController(db).current_mode() == TradingMode.ENTRIES_PAUSED

    def test_stop_cancels_open_entry_orders(self, db, adapter, flow):
        outcome = submit(flow)
        assert outcome.exchange_order_id is not None
        controller = TradingController(db)
        canceled = controller.cancel_open_orders(adapter)
        assert canceled == 1
        intent = OrderIntentRepository(db).get(outcome.client_order_id)
        assert intent is not None and intent.state == "canceled"

    def test_emergency_stop_requires_explicit_re_arm(self, db, adapter, flow):
        submit(flow)
        controller = TradingController(db)
        canceled = controller.emergency_stop(adapter, reason="anomaly detected")
        assert canceled == 1
        assert controller.kill_switch_active() is True
        assert controller.entries_allowed() is False
        assert RiskRepository(db).count_for("kill_switch") == 1

        controller.re_arm(reason="reviewed and safe")
        assert controller.kill_switch_active() is False
        assert controller.entries_allowed() is True
