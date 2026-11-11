"""Repositories: the only write path into durable state (architecture.md §14).

Repositories own the mapping between domain types (``market_data``,
``exchange``) and rows, and use the database's transactional sessions.
Replayed/duplicate inserts are deduplicated at the storage boundary via
unique constraints (ON CONFLICT DO NOTHING), never by "check then insert".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult

from trendbot.database.models import (
    AppSetting,
    CandleRecord,
    EngineEvent,
    FillRecord,
    utc_now,
)
from trendbot.database.session import Database
from trendbot.exchange.types import Fill
from trendbot.market_data.candles import Candle


def fill_entry_key(fill: Fill) -> str:
    """Composite storage identity for a fill (documented, stable format).

    The exchange-side ``entry_id`` from the verified fills schema is not
    carried on the typed ``Fill`` yet (added with the reconciliation
    sprint), so the identity combines the two immutable ids we have.
    """
    return f"{fill.exchange_order_id}:{fill.trade_id}"


class CandleRepository:
    """Persists validated candles; duplicates are safely skipped."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_many(self, candles: list[Candle], *, source: str = "exchange") -> int:
        """Insert candles, skipping duplicates on the unique candle key.

        Returns the number of newly stored candles. Dedup happens inside
        the database (``uq_candle_key``), so a replayed import never
        duplicates rows.
        """
        if not candles:
            return 0
        inserted = 0
        with self._db.session() as session:
            for candle in candles:
                statement = (
                    sqlite_insert(CandleRecord)
                    .values(
                        product_id=candle.product_id,
                        granularity=candle.granularity,
                        start_time=candle.start_time,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                        is_complete=candle.is_complete,
                        source=source,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["product_id", "granularity", "start_time"]
                    )
                )
                inserted += int(
                    cast("CursorResult[Any]", session.execute(statement)).rowcount or 0
                )
        return inserted

    def get_range(
        self, product_id: str, granularity: str, start: datetime, end: datetime
    ) -> list[Candle]:
        """Return candles with ``start_time`` in ``[start, end)``, oldest first."""
        with self._db.session() as session:
            rows = session.scalars(
                select(CandleRecord)
                .where(
                    CandleRecord.product_id == product_id,
                    CandleRecord.granularity == granularity,
                    CandleRecord.start_time >= start,
                    CandleRecord.start_time < end,
                )
                .order_by(CandleRecord.start_time)
            ).all()
        return [
            Candle(
                product_id=row.product_id,
                granularity=row.granularity,
                start_time=row.start_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                is_complete=row.is_complete,
            )
            for row in rows
        ]

    def count(self) -> int:
        with self._db.session() as session:
            return int(session.scalar(select(func.count()).select_from(CandleRecord)) or 0)

    def latest_start(self, product_id: str, granularity: str) -> datetime | None:
        """Newest stored candle start for the product/timeframe (freshness)."""
        with self._db.session() as session:
            return session.scalar(
                select(CandleRecord.start_time)
                .where(
                    CandleRecord.product_id == product_id,
                    CandleRecord.granularity == granularity,
                )
                .order_by(CandleRecord.start_time.desc())
                .limit(1)
            )

    def latest_complete_start(self, product_id: str, granularity: str) -> datetime | None:
        """Newest stored **complete** candle start (freshness gate input)."""
        with self._db.session() as session:
            return session.scalar(
                select(CandleRecord.start_time)
                .where(
                    CandleRecord.product_id == product_id,
                    CandleRecord.granularity == granularity,
                    CandleRecord.is_complete.is_(True),
                )
                .order_by(CandleRecord.start_time.desc())
                .limit(1)
            )


class FillRepository:
    """Idempotent fill storage keyed on the composite fill identity."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def record_fill(self, fill: Fill) -> bool:
        """Store one confirmed fill. Returns True if newly recorded.

        Replayed fill events (same identity) return False and never
        double-count (roadmap Sprint 2 verification).
        """
        statement = (
            sqlite_insert(FillRecord)
            .values(
                entry_id=fill_entry_key(fill),
                trade_id=fill.trade_id,
                exchange_order_id=fill.exchange_order_id,
                product_id=fill.product_id,
                side=fill.side.value,
                price=fill.price,
                size=fill.size,
                commission=fill.commission,
                trade_time=fill.trade_time,
            )
            .on_conflict_do_nothing(index_elements=["entry_id"])
        )
        with self._db.session() as session:
            result = cast("CursorResult[Any]", session.execute(statement))
            return int(result.rowcount or 0) == 1


class EngineEventRepository:
    """Append-only lifecycle/health events with optional idempotency."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def append(
        self,
        *,
        event_type: str,
        component: str,
        message: str,
        detail: dict[str, object] | None = None,
        correlation_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> int:
        """Append one event and return its row id.

        When ``dedupe_key`` is set and already exists, the existing
        event's id is returned and nothing new is stored.
        """
        with self._db.session() as session:
            if dedupe_key is not None:
                existing = session.scalar(
                    select(EngineEvent.id).where(EngineEvent.dedupe_key == dedupe_key)
                )
                if existing is not None:
                    return int(existing)
            row = EngineEvent(
                event_type=event_type,
                component=component,
                message=message,
                detail=detail,
                correlation_id=correlation_id,
                dedupe_key=dedupe_key,
            )
            session.add(row)
            session.flush()
            return int(row.id)


class SettingsRepository:
    """Non-secret application settings as string key/value pairs."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._db.session() as session:
            row = session.get(AppSetting, key)
        return default if row is None else row.value

    def set(self, key: str, value: str) -> None:
        statement = (
            sqlite_insert(AppSetting)
            .values(key=key, value=value, updated_at=utc_now())
            .on_conflict_do_update(
                index_elements=["key"], set_={"value": value, "updated_at": utc_now()}
            )
        )
        with self._db.session() as session:
            session.execute(statement)
