"""Live arming flow tests (roadmap Sprint 10)."""

from decimal import Decimal

import pytest

from trendbot.application.live_trading import LiveArmingController
from trendbot.database import Database, upgrade_to_head
from trendbot.database.repositories import OrderIntentRepository


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "arming.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def controller(db):
    return LiveArmingController(db)


def passing(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "credentials_valid": True,
        "trade_permission": True,
        "fresh_market_data": True,
        "risk_limits_acknowledged": True,
    }
    values.update(overrides)
    return values


class TestPrerequisites:
    def test_all_passing_allows_the_request(self, controller):
        result = controller.request_arm(**passing())
        assert result.requested is True
        assert result.token is not None

    def test_missing_trade_permission_blocks_the_request(self, controller):
        result = controller.request_arm(**passing(trade_permission=False))
        assert result.requested is False
        assert "Trade permission" in result.message

    def test_invalid_credentials_block_the_request(self, controller):
        result = controller.request_arm(**passing(credentials_valid=False))
        assert result.requested is False
        assert "credentials" in result.message.lower()

    def test_stale_market_data_blocks_the_request(self, controller):
        result = controller.request_arm(**passing(fresh_market_data=False))
        assert result.requested is False
        assert "stale" in result.message.lower()

    def test_unacknowledged_risk_limits_block_the_request(self, controller):
        result = controller.request_arm(**passing(risk_limits_acknowledged=False))
        assert result.requested is False
        assert "risk limits" in result.message.lower()

    def test_unresolved_intents_block_the_request(self, db, controller):
        intents = OrderIntentRepository(db)
        intents.create(
            client_order_id="stuck-1",
            product_id="BTC-USD",
            side="buy",
            base_size=Decimal("0.001"),
        )
        intents.mark("stuck-1", "risk_approved")
        intents.mark("stuck-1", "submitting")
        intents.mark("stuck-1", "unknown_submission")
        intents.mark("stuck-1", "reconciliation_required")
        result = controller.request_arm(**passing())
        assert result.requested is False
        assert "reconcile" in result.message.lower()

    def test_trade_permission_requires_the_exact_value(self, controller):
        result = controller.request_arm(
            **passing(trade_permission=True),  # exact match required
        )
        assert result.requested is True


class TestTwoStepArm:
    def test_request_then_confirm_arms(self, controller):
        request = controller.request_arm(**passing())
        assert request.token is not None
        confirmation = controller.confirm_arm(request.token or "")
        assert confirmation.requested is True
        assert controller.is_armed() is True

    def test_wrong_token_does_not_arm(self, controller):
        controller.request_arm(**passing())
        confirmation = controller.confirm_arm("wrong-token")
        assert confirmation.requested is False
        assert controller.is_armed() is False

    def test_arm_request_expires_after_five_minutes(self, controller):
        from datetime import UTC, datetime

        request = controller.request_arm(
            **passing(),
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert request.token is not None
        confirmation = controller.confirm_arm(
            request.token or "",
            now=datetime(2026, 1, 1, 6, tzinfo=UTC),  # 6 hours later
        )
        assert confirmation.requested is False
        assert "expired" in confirmation.message.lower()

    def test_disarm_after_arm(self, controller):
        request = controller.request_arm(**passing())
        controller.confirm_arm(request.token or "")
        assert controller.is_armed() is True
        controller.disarm(reason="test")
        assert controller.is_armed() is False


class TestRestartDisarm:
    def test_startup_force_disarm_never_resumes_live(self, db):
        controller = LiveArmingController(db)
        request = controller.request_arm(**passing())
        controller.confirm_arm(request.token or "")
        assert controller.is_armed() is True

        # Engine restart: a fresh controller calls force_disarm.
        restarted = LiveArmingController(db)
        restarted.force_disarm()
        assert restarted.is_armed() is False

        # And the original controller instance sees it too.
        assert controller.is_armed() is False
