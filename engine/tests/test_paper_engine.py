"""Paper trading tests (roadmap Sprint 9 verification).

The crossover decision fires on the jump candle (index 50 in the fixture),
so candles are added progressively: seed the flat run, then feed the jump
candle (BUY decision), then the next candle (fill at its open).
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.database import Database, upgrade_to_head
from trendbot.database.repositories import CandleRepository, PositionRepository
from trendbot.exchange.fake import FakeExchangeAdapter
from trendbot.exchange.types import Fill, OrderSide
from trendbot.market_data.candles import Candle
from trendbot.paper.account import PaperAccount, ResetNotConfirmedError
from trendbot.paper.engine import PaperTradingEngine
from trendbot.strategies.config import EmaRsiConfig

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
HOURLY = timedelta(hours=1)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "paper.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def adapter() -> FakeExchangeAdapter:
    return FakeExchangeAdapter()


def candles_upto(count: int) -> list[Candle]:
    """49 candles at 60, one dip to 55 (index 49), then rises from 200."""
    closes = [Decimal(60)] * 49 + [Decimal(55)] + [
        Decimal(200 + index - 50) for index in range(50, count)
    ]
    return [
        Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + index * HOURLY,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=Decimal(1),
        )
        for index, close in enumerate(closes[:count])
    ]


def make_engine(db: Database, adapter: FakeExchangeAdapter, **overrides) -> PaperTradingEngine:
    return PaperTradingEngine(
        db,
        adapter,
        config=EmaRsiConfig(product_id="BTC-USD", timeframe="1h", rsi_entry_ceiling=97.0),
        assumptions=FeeAssumptions(fee_bps=100.0, slippage_bps=0.0),
        starting_quote=Decimal("1000"),
        position_size_quote=Decimal("500"),
        poll_seconds=0.0,
        **overrides,
    )


def step(db: Database, engine: PaperTradingEngine, count: int, *, now: datetime) -> str | None:
    """Add candles up to `count` total, then process once."""
    all_candles = candles_upto(count)
    stored = CandleRepository(db).get_range("BTC-USD", "ONE_HOUR", START, START + count * HOURLY)
    fresh = all_candles[len(stored):]
    if fresh:
        CandleRepository(db).upsert_many(fresh)
    return engine.process_once(now=now)


class TestPaperLoop:
    def test_buy_fills_at_next_open_with_fees(self, db, adapter):
        engine = make_engine(db, adapter)
        step(db, engine, 50, now=START + timedelta(hours=50))  # seed: flat + dip
        step(db, engine, 51, now=START + timedelta(hours=51))  # jump candle → BUY pending
        step(db, engine, 52, now=START + timedelta(hours=52))  # fill at open 201

        position = PositionRepository(db).get("BTC-USD")
        assert position is not None and position.size == Decimal("2.5")
        # Cash paid: base 2.5 × fill 201 = 502.5 notional + 1% fee (5.025).
        assert PaperAccount(db).cash() == Decimal("492.475")
        for row in PaperAccount(db).snapshots():
            assert row.account_kind == "paper"

    def test_fees_are_charged_on_entry(self, db, adapter):
        engine = make_engine(db, adapter)
        step(db, engine, 50, now=START + timedelta(hours=50))
        step(db, engine, 51, now=START + timedelta(hours=51))
        step(db, engine, 52, now=START + timedelta(hours=52))
        assert PaperAccount(db).cash() == Decimal("492.475")  # 1000 - 502.5 - 5.025


class TestExit:
    @staticmethod
    def seed_long_position(db: Database, adapter: FakeExchangeAdapter) -> PaperAccount:
        """Paper account with a long 2.5 position and 495 cash (post-entry)."""
        account = PaperAccount(db)
        account.ensure_session()
        account.apply_entry(Decimal("500"), Decimal("5"))
        from trendbot.database.repositories import ExchangeOrderRepository, FillRepository

        ExchangeOrderRepository(db).record(
            client_order_id="seed-intent",
            exchange_order_id="seed-000001",
            product_id="BTC-USD",
            side="buy",
            status="FILLED",
        )
        fill = Fill(
            exchange_order_id="seed-000001",
            trade_id="seed-trade-1",
            product_id="BTC-USD",
            side=OrderSide.BUY,
            price=Decimal("100"),
            size=Decimal("2.5"),
            commission=Decimal("5"),
            trade_time=datetime.now(UTC),
        )
        FillRepository(db).record_fill(fill)
        PositionRepository(db).apply_fill(fill)
        return account

    @staticmethod
    def crafted_bearish_window() -> list[Candle]:
        """50 candles at 65, then 50 — exact bearish cross on candle 51.

        The window must hold required_history (51) candles: 50 flat candles
        keep both EMAs exactly at 65, so the drop to 50 is a guaranteed
        bearish transition on that candle.
        """
        candles = []
        for index in range(50):
            moment = START + index * HOURLY
            candles.append(
                Candle(
                    product_id="BTC-USD",
                    granularity="ONE_HOUR",
                    start_time=moment,
                    open=Decimal(65),
                    high=Decimal(66),
                    low=Decimal(64),
                    close=Decimal(65),
                    volume=Decimal(1),
                )
            )
        candles.append(
            Candle(
                product_id="BTC-USD",
                granularity="ONE_HOUR",
                start_time=START + 51 * HOURLY,
                open=Decimal(50),
                high=Decimal(51),
                low=Decimal(49),
                close=Decimal(50),
                volume=Decimal(1),
            )
        )
        return candles

    def test_exit_fills_and_restores_cash_with_fees(self, db, adapter):
        account = self.seed_long_position(db, adapter)
        engine = make_engine(db, adapter)
        engine._window = self.crafted_bearish_window()[:50]
        engine._last_processed = START + 49 * HOURLY

        # The bearish-cross candle: SELL pending (protective exit).
        engine._process_candle(self.crafted_bearish_window()[50], START + 50 * HOURLY)
        assert engine._pending is not None and engine._pending.value == "sell"

        # Fill at the next candle's open (48): proceeds 2.5 × 48 = 120,
        # fee 1% (1.2) → cash 495 + 118.8 = 613.8.
        exit_candle = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + 51 * HOURLY,
            open=Decimal(48),
            high=Decimal(49),
            low=Decimal(47),
            close=Decimal(48),
            volume=Decimal(1),
        )
        engine._process_candle(exit_candle, START + 51 * HOURLY)
        assert engine._position_size() == Decimal("0")
        assert account.cash() == pytest.approx(Decimal("613.8"), abs=Decimal("0.01"))


class TestIsolation:
    def test_paper_module_never_imports_the_real_coinbase_client(self):
        from pathlib import Path

        paper_root = Path(__file__).resolve().parents[1] / "src" / "trendbot" / "paper"
        for source in paper_root.rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            assert "coinbase_rest" not in text, f"{source.name} imports the real client"
            assert "CoinbaseRestClient" not in text, f"{source.name} imports the real client"

    def test_paper_snapshots_are_never_exchange_balances(self, db):
        account = PaperAccount(db)
        account.ensure_session()
        account.record_equity(Decimal("1234"))
        for row in account.snapshots():
            assert row.account_kind == "paper"
            assert row.account_kind != "exchange"


class TestRestart:
    def test_state_survives_a_restart(self, db, adapter):
        engine = make_engine(db, adapter)
        step(db, engine, 50, now=START + timedelta(hours=50))
        step(db, engine, 51, now=START + timedelta(hours=51))
        step(db, engine, 52, now=START + timedelta(hours=52))
        cash_before = PaperAccount(db).cash()
        position_before = PositionRepository(db).get("BTC-USD")
        assert position_before is not None and position_before.size == Decimal("2.5")

        # "Restart": a brand-new engine adopts persisted state.
        restarted = make_engine(db, adapter)
        restarted.process_once(now=START + timedelta(hours=53))
        assert PaperAccount(db).cash() == cash_before
        position_after = PositionRepository(db).get("BTC-USD")
        assert position_after is not None and position_after.size == Decimal("2.5")

    def test_mode_persists_across_restart(self, db):
        from trendbot.application.trading_controls import TradingController, TradingMode

        controller = TradingController(db)
        controller.set_mode(TradingMode.ENTRIES_PAUSED, reason="test")
        assert TradingController(db).current_mode() == TradingMode.ENTRIES_PAUSED


class TestPauseBehavior:
    def test_paused_entries_are_suppressed_but_exits_continue(self, db, adapter):
        from trendbot.application.trading_controls import TradingController, TradingMode

        TestExit.seed_long_position(db, adapter)
        engine = make_engine(db, adapter)
        engine._window = TestExit.crafted_bearish_window()[:50]
        engine._last_processed = START + 49 * HOURLY

        controller = TradingController(db)
        controller.set_mode(TradingMode.ENTRIES_PAUSED, reason="test")
        assert controller.entries_allowed() is False

        # Bearish cross while paused: the protective exit still fires.
        engine._process_candle(TestExit.crafted_bearish_window()[50], START + 50 * HOURLY)
        assert engine._pending is not None and engine._pending.value == "sell"

        exit_candle = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + 51 * HOURLY,
            open=Decimal(48),
            high=Decimal(49),
            low=Decimal(47),
            close=Decimal(48),
            volume=Decimal(1),
        )
        engine._process_candle(exit_candle, START + 51 * HOURLY)
        assert engine._position_size() == Decimal("0")


class TestResetAndExport:
    def test_reset_requires_confirmation(self, db):
        account = PaperAccount(db)
        account.ensure_session()
        with pytest.raises(ResetNotConfirmedError):
            account.reset()
        account.reset(confirm=True)
        assert account.cash() == Decimal("1000")

    def test_export_is_json_safe_and_paper_scoped(self, db):
        account = PaperAccount(db)
        account.ensure_session()
        account.record_equity(Decimal("1500"))
        state = account.export_state()
        assert state["account_kind"] == "paper"
        assert state["cash"] == str(account.cash())
        json.dumps(state)
