"""The paper account: isolated simulated funds, fully persisted (task 1).

Current cash lives in ``app_settings`` (fast access); every cash-changing
event appends a ``balance_snapshots`` row with ``account_kind="paper"`` —
paper balances are structurally distinct from exchange snapshots and are
never rendered as exchange balances. Reset requires an explicit
confirmation flag (roadmap Sprint 9 task 8).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select

from trendbot.database.models import BalanceSnapshot
from trendbot.database.repositories import SettingsRepository
from trendbot.database.session import Database

CASH_KEY = "paper_cash"
SESSION_START_KEY = "paper_session_started_at"
STARTING_BALANCE_KEY = "paper_starting_balance"
PAPER_ACCOUNT_KIND = "paper"
DEFAULT_STARTING_QUOTE = Decimal("1000")


class ResetNotConfirmedError(RuntimeError):
    """Paper-state reset was called without ``confirm=True``."""


class PaperAccount:
    """The simulated trading account."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._settings = SettingsRepository(database)

    def ensure_session(
        self, starting_quote: Decimal = DEFAULT_STARTING_QUOTE, *, now: datetime | None = None
    ) -> bool:
        """Start a paper session if none exists. Returns True when created."""
        moment = now or datetime.now(UTC)
        if self._settings.get(SESSION_START_KEY) is not None:
            return False
        if self._settings.get(CASH_KEY) is None:
            self._settings.set(CASH_KEY, str(starting_quote))
            self._settings.set(STARTING_BALANCE_KEY, str(starting_quote))
            self._snapshot(moment, starting_quote, note="session_start")
        self._settings.set(SESSION_START_KEY, moment.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return True

    def cash(self) -> Decimal:
        raw = self._settings.get(CASH_KEY)
        return Decimal(raw) if raw else DEFAULT_STARTING_QUOTE

    def starting_balance(self) -> Decimal:
        raw = self._settings.get(STARTING_BALANCE_KEY)
        return Decimal(raw) if raw else DEFAULT_STARTING_QUOTE

    def session_started_at(self) -> str | None:
        return self._settings.get(SESSION_START_KEY)

    def apply_entry(self, notional: Decimal, fee: Decimal, *, now: datetime | None = None) -> None:
        cash = self.cash() - notional - fee
        self._settings.set(CASH_KEY, str(cash))
        self._snapshot(now or datetime.now(UTC), cash, note="entry")

    def apply_exit(self, proceeds: Decimal, fee: Decimal, *, now: datetime | None = None) -> None:
        cash = self.cash() + proceeds - fee
        self._settings.set(CASH_KEY, str(cash))
        self._snapshot(now or datetime.now(UTC), cash, note="exit")

    def record_equity(self, equity: Decimal, *, now: datetime | None = None) -> None:
        self._snapshot(now or datetime.now(UTC), equity, note="mark")

    def snapshots(self, limit: int = 50) -> list[BalanceSnapshot]:
        with self._db.session() as session:
            rows = session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_kind == PAPER_ACCOUNT_KIND)
                .order_by(BalanceSnapshot.captured_at.desc(), BalanceSnapshot.id.desc())
                .limit(limit)
            ).all()
            return list(rows)

    def reset(self, *, confirm: bool = False) -> None:
        """Wipe paper state and start a fresh session. Requires confirmation."""
        if not confirm:
            raise ResetNotConfirmedError(
                "Resetting the paper account wipes simulated balances, positions, "
                "and history. Call again with confirm=true to proceed."
            )
        with self._db.session() as session:
            session.execute(
                delete(BalanceSnapshot).where(BalanceSnapshot.account_kind == PAPER_ACCOUNT_KIND)
            )
        self._settings.set(CASH_KEY, str(DEFAULT_STARTING_QUOTE))
        self._settings.set(STARTING_BALANCE_KEY, str(DEFAULT_STARTING_QUOTE))
        self._settings.set(SESSION_START_KEY, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._snapshot(datetime.now(UTC), DEFAULT_STARTING_QUOTE, note="reset")

    def export_state(self) -> dict[str, object]:
        """JSON-safe paper state for export (no secrets by construction)."""
        snapshots = [self._snapshot_dict(row) for row in self.snapshots(limit=200)]
        return {
            "account_kind": PAPER_ACCOUNT_KIND,
            "cash": str(self.cash()),
            "starting_balance": str(self.starting_balance()),
            "session_started_at": self.session_started_at(),
            "snapshots": snapshots,
        }

    def _snapshot(self, moment: datetime, equity: Decimal, *, note: str) -> None:
        with self._db.session() as session:
            session.add(
                BalanceSnapshot(
                    account_kind=PAPER_ACCOUNT_KIND,
                    currency="USD",
                    available=equity,
                    hold=Decimal(0),
                    captured_at=moment,
                )
            )

    @staticmethod
    def _snapshot_dict(row: BalanceSnapshot) -> dict[str, object]:
        return {
            "account_kind": row.account_kind,
            "currency": row.currency,
            "available": str(row.available),
            "captured_at": row.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
