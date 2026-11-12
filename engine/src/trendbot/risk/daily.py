"""Daily PnL accounting: persisted UTC-day baseline and drawdown (task 4).

The baseline is the first equity snapshot recorded for the UTC day and is
**persisted** — an app restart never resets the drawdown accounting
(architecture.md §9). Deposits/withdrawals or manual trades make
attribution uncertain: rows get flagged when external flows are reported.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from trendbot.database.models import DailyAccounting
from trendbot.database.session import Database


class DailyLedger:
    """Persists the daily equity baseline and current drawdown."""

    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _day(now: datetime) -> str:
        return now.astimezone(UTC).strftime("%Y-%m-%d")

    def record_equity(
        self, equity: Decimal, *, now: datetime | None = None, external_flows: Decimal | None = None
    ) -> Decimal:
        """Record one equity snapshot; returns the current drawdown percent.

        The first snapshot of the UTC day fixes the baseline; later
        snapshots update the drawdown without moving the baseline.
        """
        moment = now or datetime.now(UTC)
        day = self._day(moment)
        with self._db.session() as session:
            row = session.scalars(
                select(DailyAccounting).where(DailyAccounting.day == day)
            ).first()
            if row is None:
                row = DailyAccounting(
                    day=day,
                    baseline_equity=equity,
                    external_flows=external_flows or Decimal(0),
                    flagged=external_flows not in (None, Decimal(0)),
                )
                session.add(row)
            else:
                if row.baseline_equity is None:
                    row.baseline_equity = equity
                if external_flows not in (None, Decimal(0)):
                    row.external_flows = (row.external_flows or Decimal(0)) + external_flows
                    row.flagged = True
            baseline = row.baseline_equity or equity
            drawdown = self._drawdown(baseline, equity)
            row.drawdown_percent = drawdown
            session.flush()
            return drawdown

    def drawdown_pct(self, equity: Decimal, *, now: datetime | None = None) -> Decimal:
        """Current drawdown for the UTC day (0 when no baseline exists)."""
        day = self._day(now or datetime.now(UTC))
        with self._db.session() as session:
            row = session.scalars(
                select(DailyAccounting).where(DailyAccounting.day == day)
            ).first()
        if row is None or row.baseline_equity is None:
            return Decimal(0)
        return self._drawdown(row.baseline_equity, equity)

    def baseline(self, *, now: datetime | None = None) -> Decimal | None:
        day = self._day(now or datetime.now(UTC))
        with self._db.session() as session:
            row = session.scalars(
                select(DailyAccounting).where(DailyAccounting.day == day)
            ).first()
        return None if row is None else row.baseline_equity

    @staticmethod
    def _drawdown(baseline: Decimal, equity: Decimal) -> Decimal:
        if baseline <= 0 or equity >= baseline:
            return Decimal(0)
        return (baseline - equity) / baseline * Decimal(100)
