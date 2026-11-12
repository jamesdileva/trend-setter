"""Distinct trading-control semantics (architecture.md §5; Sprint 8 task 11).

- **Pause entries**: no new entries; existing management continues.
- **Stop trading**: pause + cancel open entry orders + reconcile; still
  no forced exits.
- **Emergency stop**: kill switch — blocks everything new, cancels open
  orders, requires an explicit re-arm before anything resumes.
- **Exit all**: separate, explicit action closing positions through the
  same durable intent flow.

The mode and kill switch persist in ``app_settings``: a restart never
silently resumes live trading (R-06).
"""

from __future__ import annotations

from enum import StrEnum

from trendbot.database.repositories import OrderIntentRepository, RiskRepository, SettingsRepository
from trendbot.database.session import Database
from trendbot.exchange.base import ExchangeAdapter

MODE_KEY = "trading_mode"
KILL_SWITCH_KEY = "kill_switch_active"


class TradingMode(StrEnum):
    NORMAL = "normal"
    ENTRIES_PAUSED = "entries_paused"
    STOPPED = "stopped"
    EMERGENCY_STOPPED = "emergency_stopped"


class TradingController:
    """Persists and enforces the trading control mode."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._settings = SettingsRepository(database)
        self._intents = OrderIntentRepository(database)
        self._risk_events = RiskRepository(database)

    def current_mode(self) -> TradingMode:
        raw = self._settings.get(MODE_KEY) or TradingMode.NORMAL.value
        try:
            return TradingMode(raw)
        except ValueError:
            return TradingMode.NORMAL

    def entries_allowed(self) -> bool:
        return self.current_mode() == TradingMode.NORMAL and not self.kill_switch_active()

    def set_mode(self, mode: TradingMode, *, reason: str = "") -> None:
        self._settings.set(MODE_KEY, mode.value)
        self._risk_events.record(
            event_kind=f"trading_mode_{mode.value}",
            detail={"reason": reason} if reason else None,
        )
        if mode == TradingMode.EMERGENCY_STOPPED:
            self._settings.set(KILL_SWITCH_KEY, "true")
            self._risk_events.record(
                event_kind="kill_switch",
                detail={"reason": reason} if reason else None,
            )

    def kill_switch_active(self) -> bool:
        return self._settings.get(KILL_SWITCH_KEY) == "true"

    def re_arm(self, *, reason: str = "") -> None:
        """Explicit re-arm after emergency stop (never automatic)."""
        self._settings.set(KILL_SWITCH_KEY, "false")
        self._settings.set(MODE_KEY, TradingMode.NORMAL.value)
        self._risk_events.record(
            event_kind="kill_switch_rearmed",
            detail={"reason": reason} if reason else None,
        )

    def emergency_stop(
        self, adapter: ExchangeAdapter, *, reason: str = "manual emergency stop"
    ) -> int:
        """Kill switch + cancel all open orders. Returns canceled count."""
        self.set_mode(TradingMode.EMERGENCY_STOPPED, reason=reason)
        return self.cancel_open_orders(adapter)

    def cancel_open_orders(self, adapter: ExchangeAdapter) -> int:
        """Cancel every unresolved open order intent; returns successes."""
        canceled = 0
        for intent in self._intents.list_unresolved():
            if intent.state not in ("open", "acknowledged", "partially_filled"):
                continue
            exchange_id = ExchangeOrderLookup(self._db).exchange_id_for(intent.client_order_id)
            if exchange_id is None:
                continue
            if adapter.cancel_order(exchange_id):
                self._intents.mark(intent.client_order_id, "cancel_pending")
                self._intents.mark(intent.client_order_id, "canceled")
                canceled += 1
        return canceled


class ExchangeOrderLookup:
    def __init__(self, database: Database) -> None:
        from trendbot.database.repositories import ExchangeOrderRepository

        self._repo = ExchangeOrderRepository(database)

    def exchange_id_for(self, client_order_id: str) -> str | None:
        return self._repo.exchange_id_for(client_order_id)
