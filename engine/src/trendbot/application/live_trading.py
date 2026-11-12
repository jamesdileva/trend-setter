"""Live trading arming: multi-step, prerequisite-gated, restart-disarmed
(architecture.md §13; roadmap Sprint 10).

Arming is a deliberate two-step flow: ``request_arm`` stores a pending
arm with a one-time token (after checking every prerequisite); the
caller must then present that token to ``confirm_arm``. Every engine
startup forces the armed state back to disarmed — a restart never
silently resumes live trading (R-06).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trendbot.database.repositories import (
    OrderIntentRepository,
    RiskRepository,
    SettingsRepository,
)
from trendbot.database.session import Database

ARMED_KEY = "live_armed"
ARM_PENDING_KEY = "live_arm_pending"
CREDENTIALS_KEY = "coinbase_credentials_valid"


@dataclass(frozen=True)
class ArmPrerequisites:
    """The checks that must all pass before arming is even requestable."""

    credentials_valid: bool
    trade_permission: bool
    reconciliation_clean: bool
    fresh_market_data: bool
    risk_limits_acknowledged: bool

    @property
    def all_pass(self) -> bool:
        return (
            self.credentials_valid
            and self.trade_permission
            and self.reconciliation_clean
            and self.fresh_market_data
            and self.risk_limits_acknowledged
        )

    def failures(self) -> list[str]:
        messages: list[str] = []
        if not self.credentials_valid:
            messages.append("Coinbase credentials are not connected or have expired.")
        if not self.trade_permission:
            messages.append("The connected key lacks the Trade permission.")
        if not self.reconciliation_clean:
            messages.append("There are unresolved order intents — reconcile first.")
        if not self.fresh_market_data:
            messages.append("Market data is stale — the freshness gate must pass.")
        if not self.risk_limits_acknowledged:
            messages.append("The risk limits must be reviewed and acknowledged.")
        return messages


@dataclass(frozen=True)
class ArmRequestResult:
    requested: bool
    token: str | None
    message: str


class LiveArmingController:
    """Gates live execution behind prerequisites and a two-step arm."""

    def __init__(
        self,
        database: Database,
        *,
        product_ids: list[str] | None = None,
        max_order_quote: Decimal = Decimal("100"),
    ) -> None:
        self._db = database
        self._settings = SettingsRepository(database)
        self._intents = OrderIntentRepository(database)
        self._risk_events = RiskRepository(database)
        self.product_ids = product_ids or ["BTC-USD"]
        self.max_order_quote = max_order_quote

    # -- state ---------------------------------------------------------

    def is_armed(self) -> bool:
        return self._settings.get(ARMED_KEY) == "true"

    def force_disarm(self, *, reason: str = "engine startup") -> None:
        """Unconditionally disarm — called on every engine startup (R-06)."""
        self._settings.set(ARMED_KEY, "false")
        self._settings.set(ARM_PENDING_KEY, "")
        self._risk_events.record(
            event_kind="live_disarmed_on_startup",
            detail={"reason": reason},
        )

    def disarm(self, *, reason: str = "manual disarm") -> None:
        self._settings.set(ARMED_KEY, "false")
        self._settings.set(ARM_PENDING_KEY, "")
        self._risk_events.record(
            event_kind="live_disarmed",
            detail={"reason": reason} if reason else None,
        )

    # -- prerequisites ---------------------------------------------------

    def check_prerequisites(
        self,
        *,
        credentials_valid: bool,
        trade_permission: bool,
        fresh_market_data: bool,
        risk_limits_acknowledged: bool,
    ) -> ArmPrerequisites:
        """Gather the arming prerequisites (caller supplies credentials/gate state)."""
        unresolved = self._intents.list_unresolved()
        return ArmPrerequisites(
            credentials_valid=credentials_valid,
            trade_permission=trade_permission,
            reconciliation_clean=len(unresolved) == 0,
            fresh_market_data=fresh_market_data,
            risk_limits_acknowledged=risk_limits_acknowledged,
        )

    # -- arm flow ----------------------------------------------------------

    def request_arm(
        self,
        *,
        credentials_valid: bool,
        trade_permission: bool,
        fresh_market_data: bool,
        risk_limits_acknowledged: bool,
        product_ids: list[str] | None = None,
        now: datetime | None = None,
    ) -> ArmRequestResult:
        """Step 1: check prerequisites and store a one-time arm token."""
        prereqs = self.check_prerequisites(
            credentials_valid=credentials_valid,
            trade_permission=trade_permission,
            fresh_market_data=fresh_market_data,
            risk_limits_acknowledged=risk_limits_acknowledged,
        )
        if not prereqs.all_pass:
            return ArmRequestResult(
                requested=False,
                token=None,
                message="; ".join(prereqs.failures()),
            )
        token = uuid.uuid4().hex
        payload = {
            "token": token,
            "product_ids": product_ids or self.product_ids,
            "max_order_quote": str(self.max_order_quote),
            "requested_at": (now or datetime.now(UTC)).isoformat(),
        }
        import json

        self._settings.set(ARM_PENDING_KEY, json.dumps(payload))
        self._risk_events.record(
            event_kind="live_arm_requested",
            detail={"product_ids": payload["product_ids"]},
        )
        return ArmRequestResult(
            requested=True,
            token=token,
            message="Arm request pending confirmation.",
        )

    def confirm_arm(self, token: str, *, now: datetime | None = None) -> ArmRequestResult:
        """Step 2: present the token to actually arm live trading."""
        import json

        raw = self._settings.get(ARM_PENDING_KEY)
        if not raw:
            return ArmRequestResult(
                requested=False, token=None, message="No pending arm request. Start with a request."
            )
        pending = json.loads(raw)
        if pending.get("token") != token:
            return ArmRequestResult(
                requested=False, token=None, message="The confirmation token does not match."
            )
        requested_at = datetime.fromisoformat(pending["requested_at"])
        if (now or datetime.now(UTC)) - requested_at > timedelta(minutes=5):
            self._settings.set(ARM_PENDING_KEY, "")
            return ArmRequestResult(
                requested=False,
                token=None,
                message="The arm request expired (5 minutes). Start again.",
            )
        self._settings.set(ARM_PENDING_KEY, "")
        self._settings.set(ARMED_KEY, "true")
        self._risk_events.record(
            event_kind="live_armed",
            detail={"product_ids": pending.get("product_ids")},
        )
        return ArmRequestResult(
            requested=True,
            token=token,
            message="Live trading is ARMED. Orders will be placed with real funds.",
        )
