"""SQLAlchemy models for the durable local database (architecture.md §14).

Conventions enforced by this module:

- Money and quantities are stored as decimal strings (``DecimalString``) —
  never binary floats (persistence rule 1).
- Timestamps are UTC (``UtcDateTime``).
- Unique constraints prevent duplicate candles, fills, and event
  processing (persistence rule 3).
- Order/fill history is immutable; corrections are additive audit events
  (persistence rule 4) — models here never get UPDATE flows for history.

``credential_metadata`` deliberately has no column that could hold secret
material: only a non-secret reference and status (architecture.md §14).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from trendbot.database.types import DecimalString, UtcDateTime


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    """Non-secret application settings (secrets live in the OS credential store)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now
    )


class CredentialMetadata(Base):
    """Credential reference and status only — never private key material."""

    __tablename__ = "credential_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String, default="coinbase")
    key_reference: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    permissions: Mapped[str | None] = mapped_column(String, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("provider", "key_reference", name="uq_credential_ref"),)


class ProductRecord(Base):
    """Supported product metadata and increments (verified Coinbase fields)."""

    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    base_increment: Mapped[Decimal] = mapped_column(DecimalString)
    quote_increment: Mapped[Decimal] = mapped_column(DecimalString)
    price_increment: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    base_min_size: Mapped[Decimal] = mapped_column(DecimalString)
    base_max_size: Mapped[Decimal] = mapped_column(DecimalString)
    quote_min_size: Mapped[Decimal] = mapped_column(DecimalString)
    quote_max_size: Mapped[Decimal] = mapped_column(DecimalString)
    limit_only: Mapped[bool] = mapped_column(Boolean, default=False)
    post_only: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_only: Mapped[bool] = mapped_column(Boolean, default=False)
    trading_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="active")
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class CandleRecord(Base):
    """Validated OHLCV candles; deduplicated on product/interval/time."""

    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(String)
    granularity: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime] = mapped_column(UtcDateTime)
    open: Mapped[Decimal] = mapped_column(DecimalString)
    high: Mapped[Decimal] = mapped_column(DecimalString)
    low: Mapped[Decimal] = mapped_column(DecimalString)
    close: Mapped[Decimal] = mapped_column(DecimalString)
    volume: Mapped[Decimal] = mapped_column(DecimalString)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String, default="exchange")
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("product_id", "granularity", "start_time", name="uq_candle_key"),
    )


class StrategyConfig(Base):
    """Versioned strategy settings with a content hash (architecture.md §8)."""

    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("name", "config_hash", name="uq_strategy_config_content"),
    )


class Signal(Base):
    """One strategy decision with its indicator evidence (architecture.md §8)."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(String)
    granularity: Mapped[str] = mapped_column(String)
    strategy_config_id: Mapped[int] = mapped_column(ForeignKey("strategy_configs.id"))
    candle_start_time: Mapped[datetime] = mapped_column(UtcDateTime)
    decision: Mapped[str] = mapped_column(String)
    reason_code: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(Text)
    indicator_values: Mapped[dict[str, str]] = mapped_column(JSON)
    strategy_version: Mapped[str] = mapped_column(String)
    config_hash: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    __table_args__ = (
        Index("ix_signals_product_time", "product_id", "candle_start_time"),
        # One signal per strategy-config content per candle: repeated
        # evaluation of the same candle never duplicates rows (Sprint 6).
        UniqueConstraint(
            "product_id",
            "granularity",
            "config_hash",
            "candle_start_time",
            name="uq_signal_per_candle",
        ),
    )


class OrderIntent(Base):
    """Durable local order request and its risk decision (architecture.md §10).

    Persisted before any network submission; ``client_order_id`` is the
    idempotency identity. State transitions arrive with the execution sprint.
    """

    __tablename__ = "order_intents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String, unique=True)
    product_id: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    order_kind: Mapped[str] = mapped_column(String, default="limit")
    base_size: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    quote_size: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    limit_price: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    state: Mapped[str] = mapped_column(String, default="created")
    risk_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now
    )


class ExchangeOrder(Base):
    """Exchange order ids, statuses, and timestamps — exchange state wins."""

    __tablename__ = "exchange_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange_order_id: Mapped[str] = mapped_column(String, unique=True)
    client_order_id: Mapped[str] = mapped_column(String)
    order_intent_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_intents.id"), nullable=True
    )
    product_id: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    filled_size: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0"))
    average_filled_price: Mapped[Decimal | None] = mapped_column(
        DecimalString, nullable=True
    )
    total_fees: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    created_time: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_update_time: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class FillRecord(Base):
    """Individual confirmed executions and fees; immutable history.

    ``entry_id`` is the exchange fill identity — unique constraint makes
    fill processing idempotent (replayed events never double-count).
    """

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[str] = mapped_column(String, unique=True)
    trade_id: Mapped[str] = mapped_column(String)
    exchange_order_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_orders.exchange_order_id")
    )
    product_id: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    price: Mapped[Decimal] = mapped_column(DecimalString)
    size: Mapped[Decimal] = mapped_column(DecimalString)
    commission: Mapped[Decimal] = mapped_column(DecimalString)
    liquidity_indicator: Mapped[str | None] = mapped_column(String, nullable=True)
    trade_time: Mapped[datetime] = mapped_column(UtcDateTime)
    sequence_timestamp: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    __table_args__ = (Index("ix_fills_order", "exchange_order_id"),)


class Position(Base):
    """Derived/current position snapshot per product (exchange truth wins)."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(String, unique=True)
    side: Mapped[str | None] = mapped_column(String, nullable=True)
    size: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0"))
    average_entry_price: Mapped[Decimal | None] = mapped_column(
        DecimalString, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now
    )


class BalanceSnapshot(Base):
    """Timestamped exchange and paper balances (kept clearly separate)."""

    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_kind: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    available: Mapped[Decimal] = mapped_column(DecimalString)
    hold: Mapped[Decimal] = mapped_column(DecimalString)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    __table_args__ = (
        Index("ix_balance_snapshot", "account_kind", "currency", "captured_at"),
    )


class RiskEvent(Base):
    """Limits, rejections, and kill-switch events (architecture.md §9)."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_kind: Mapped[str] = mapped_column(String)
    product_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class EngineEvent(Base):
    """Lifecycle, connectivity, recovery, and health events.

    ``dedupe_key`` is optional; when set it makes event processing
    idempotent (unique constraint — replayed events never duplicate).
    """

    __tablename__ = "engine_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String)
    component: Mapped[str] = mapped_column(String)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class BacktestRun(Base):
    """Backtest configuration and summary metrics (architecture.md §11)."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_config_id: Mapped[int] = mapped_column(ForeignKey("strategy_configs.id"))
    product_id: Mapped[str] = mapped_column(String)
    granularity: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime] = mapped_column(UtcDateTime)
    end_time: Mapped[datetime] = mapped_column(UtcDateTime)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class BacktestTrade(Base):
    """Simulated trade-level results (architecture.md §11)."""

    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"))
    side: Mapped[str] = mapped_column(String)
    entry_time: Mapped[datetime] = mapped_column(UtcDateTime)
    exit_time: Mapped[datetime] = mapped_column(UtcDateTime)
    entry_price: Mapped[Decimal] = mapped_column(DecimalString)
    exit_price: Mapped[Decimal] = mapped_column(DecimalString)
    size: Mapped[Decimal] = mapped_column(DecimalString)
    fees: Mapped[Decimal] = mapped_column(DecimalString)
    pnl: Mapped[Decimal] = mapped_column(DecimalString)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_backtest_trades_run", "backtest_run_id"),)


class DailyAccounting(Base):
    """Daily baseline, PnL, and drawdown state (architecture.md §9).

    ``day`` is a UTC calendar date string (YYYY-MM-DD); the baseline
    survives restarts so drawdown accounting is not reset by the app.
    """

    __tablename__ = "daily_accounting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String, unique=True)
    baseline_equity: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0"))
    fees_paid: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0"))
    external_flows: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0"))
    drawdown_percent: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now
    )


CORE_TABLES: tuple[str, ...] = (
    "app_settings",
    "credential_metadata",
    "products",
    "candles",
    "strategy_configs",
    "signals",
    "order_intents",
    "exchange_orders",
    "fills",
    "positions",
    "balance_snapshots",
    "risk_events",
    "engine_events",
    "backtest_runs",
    "backtest_trades",
    "daily_accounting",
)
