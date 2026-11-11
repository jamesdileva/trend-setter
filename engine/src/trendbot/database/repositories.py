"""Repositories: the only write path into durable state (architecture.md §14).

Repositories own the mapping between domain types (``market_data``,
``exchange``) and rows, and use the database's transactional sessions.
Replayed/duplicate inserts are deduplicated at the storage boundary via
unique constraints (ON CONFLICT DO NOTHING), never by "check then insert".
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult

from trendbot.database.models import (
    AppSetting,
    BacktestRun,
    BacktestTrade,
    CandleRecord,
    EngineEvent,
    FillRecord,
    Signal,
    StrategyConfig,
    utc_now,
)
from trendbot.database.session import Database
from trendbot.exchange.types import Fill
from trendbot.market_data.candles import Candle
from trendbot.strategies.decisions import StrategyDecision


class TradeRecordLike(Protocol):
    """Structural view of a backtest trade for persistence."""

    @property
    def entry_time(self) -> datetime: ...

    @property
    def exit_time(self) -> datetime: ...

    @property
    def entry_price(self) -> Decimal: ...

    @property
    def exit_price(self) -> Decimal: ...

    @property
    def base_size(self) -> Decimal: ...

    @property
    def entry_notional(self) -> Decimal: ...

    @property
    def fee_entry(self) -> Decimal: ...

    @property
    def fee_exit(self) -> Decimal: ...

    @property
    def pnl_quote(self) -> Decimal: ...

    @property
    def note(self) -> str: ...


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


class StrategyConfigRepository:
    """Versioned strategy configurations with a single active version."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def get_active(self, name: str) -> StrategyConfig | None:
        with self._db.session() as session:
            return session.scalars(
                select(StrategyConfig)
                .where(StrategyConfig.name == name, StrategyConfig.is_active.is_(True))
                .order_by(StrategyConfig.version.desc())
                .limit(1)
            ).first()

    def get_by_hash(self, name: str, config_hash: str) -> StrategyConfig | None:
        with self._db.session() as session:
            return session.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.name == name,
                    StrategyConfig.config_hash == config_hash,
                )
            ).first()

    def save_active(
        self, name: str, config_json: dict[str, Any], config_hash: str
    ) -> StrategyConfig:
        """Store a new active version; identical content reactivates its row.

        Previous versions stay as history. Re-saving identical content does
        not create a duplicate row (same content = same version).
        """
        with self._db.session() as session:
            existing = session.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.name == name,
                    StrategyConfig.config_hash == config_hash,
                )
            ).first()
            for row in session.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.name == name, StrategyConfig.is_active.is_(True)
                )
            ):
                row.is_active = False
            if existing is not None:
                existing.is_active = True
                return existing
            latest_version = session.scalar(
                select(func.max(StrategyConfig.version)).where(StrategyConfig.name == name)
            )
            row = StrategyConfig(
                name=name,
                version=int(latest_version or 0) + 1,
                config_hash=config_hash,
                config_json=config_json,
                is_active=True,
            )
            session.add(row)
            session.flush()
            return row

    def get_or_create(
        self, name: str, config_json: dict[str, Any], config_hash: str
    ) -> StrategyConfig:
        """Fetch the row for this content, creating an (inactive) one if needed.

        Used by backtests: recording a run must never change the user's
        active configuration.
        """
        with self._db.session() as session:
            existing = session.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.name == name,
                    StrategyConfig.config_hash == config_hash,
                )
            ).first()
            if existing is not None:
                return existing
            latest_version = session.scalar(
                select(func.max(StrategyConfig.version)).where(StrategyConfig.name == name)
            )
            row = StrategyConfig(
                name=name,
                version=int(latest_version or 0) + 1,
                config_hash=config_hash,
                config_json=config_json,
                is_active=False,
            )
            session.add(row)
            session.flush()
            return row


class SignalRepository:
    """Signal persistence, idempotent per candle (uq_signal_per_candle)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def record(self, decision: StrategyDecision, strategy_config_id: int) -> int | None:
        """Store one decision; returns None when this candle already has one."""
        from datetime import UTC, datetime

        from trendbot.market_data.granularity import granularity_for_timeframe

        with self._db.session() as session:
            existing = session.scalar(
                select(Signal.id).where(
                    Signal.product_id == decision.product_id,
                    Signal.granularity == granularity_for_timeframe(decision.timeframe),
                    Signal.config_hash == decision.config_hash,
                    Signal.candle_start_time == decision.candle_time,
                )
            )
            if existing is not None:
                return None
            row = Signal(
                product_id=decision.product_id,
                granularity=granularity_for_timeframe(decision.timeframe),
                strategy_config_id=strategy_config_id,
                candle_start_time=decision.candle_time,
                decision=decision.signal.value,
                reason_code=decision.reason_code,
                explanation=decision.explanation,
                indicator_values=dict(decision.indicator_values),
                strategy_version=decision.strategy_version,
                config_hash=decision.config_hash,
                decided_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def recent(self, product_id: str, granularity: str, limit: int = 20) -> list[Signal]:
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(Signal)
                    .where(Signal.product_id == product_id, Signal.granularity == granularity)
                    .order_by(Signal.candle_start_time.desc(), Signal.id.desc())
                    .limit(limit)
                ).all()
            )


class BacktestRepository:
    """Persistence for simulation runs and their trade ledgers."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def record_run(
        self,
        *,
        strategy_config_id: int,
        product_id: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
        assumptions: dict[str, object],
        metrics: dict[str, object],
    ) -> int:
        """Store one simulation run header; returns its id."""
        from trendbot.market_data.granularity import granularity_for_timeframe

        with self._db.session() as session:
            row = BacktestRun(
                strategy_config_id=strategy_config_id,
                product_id=product_id,
                granularity=granularity_for_timeframe(timeframe),
                start_time=start_time,
                end_time=end_time,
                assumptions=assumptions,
                metrics=metrics,
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def record_trade(self, run_id: int, trade: TradeRecordLike) -> None:
        """Append one ledger entry for a run (side always long in this model)."""
        with self._db.session() as session:
            session.add(
                BacktestTrade(
                    backtest_run_id=run_id,
                    side="long",
                    entry_time=trade.entry_time,
                    exit_time=trade.exit_time,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    size=trade.base_size,
                    fees=trade.fee_entry + trade.fee_exit,
                    pnl=trade.pnl_quote,
                    reason=trade.note or "simulated",
                )
            )

    def list_runs(self, limit: int = 20) -> list[BacktestRun]:
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(BacktestRun)
                    .order_by(BacktestRun.id.desc())
                    .limit(limit)
                ).all()
            )

    def trades_for(self, run_id: int) -> list[BacktestTrade]:
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(BacktestTrade)
                    .where(BacktestTrade.backtest_run_id == run_id)
                    .order_by(BacktestTrade.entry_time)
                ).all()
            )
