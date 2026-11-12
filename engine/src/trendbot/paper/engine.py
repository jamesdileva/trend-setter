"""The paper trading engine (roadmap Sprint 9).

Runs the real pipeline — strategy evaluation, risk gate, durable
intents, idempotent fills — with simulated funds and next-open fills
(the same fee/slippage model as the backtester, so paper results and
backtest results share assumptions). Paper mode is structurally isolated:
the only exchange adapter here is the in-memory fake, and no module in
``trendbot.paper`` imports the real Coinbase client (guarded by test).

Restart policy (documented, safe direction): paper fills apply at fill
time, so persisted positions/cash already reflect everything applied.
In-flight intents from a previous session are canceled on startup (a
fresh fake has no phantom orders to reconcile) and the engine adopts
persisted positions/cash.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trendbot.application.trading_controls import TradingController, TradingMode
from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.database.repositories import CandleRepository, PositionRepository
from trendbot.database.session import Database
from trendbot.exchange.fake import FakeExchangeAdapter
from trendbot.exchange.types import OrderRequest, OrderSide
from trendbot.execution.fills import apply_fill_idempotent
from trendbot.execution.intents import IntentService
from trendbot.execution.state_machine import ACKNOWLEDGED, FILLED, OPEN, SUBMITTING
from trendbot.market_data.candles import Candle
from trendbot.market_data.granularity import granularity_for_timeframe, granularity_seconds
from trendbot.paper.account import PaperAccount
from trendbot.risk.daily import DailyLedger
from trendbot.risk.manager import RiskContext, RiskManager
from trendbot.risk.sizing import size_entry
from trendbot.strategies.config import STRATEGY_NAME, EmaRsiConfig
from trendbot.strategies.decisions import FLAT_POSITION, SignalType, StrategyPosition
from trendbot.strategies.registry import get_strategy

PAPER_WARNING = (
    "PAPER TRADING — simulated funds only. No real orders are placed and "
    "no real balances are shown. Fills are simulated with placeholder fees."
)


@dataclass
class PaperStatus:
    running: bool = False
    mode: str = TradingMode.NORMAL.value
    cash: str = "0"
    position_size: str = "0"
    position_side: str = "flat"
    equity: str = "0"
    session_pnl: str = "0"
    last_decision: str | None = None
    last_decision_reason: str | None = None
    pending: str | None = None
    processed_candles: int = 0
    details: dict[str, object] = field(default_factory=dict)

    def snapshot(self) -> dict[str, object]:
        return {
            "warning": PAPER_WARNING,
            "account_kind": "paper",
            "running": self.running,
            "mode": self.mode,
            "cash": self.cash,
            "position_size": self.position_size,
            "position_side": self.position_side,
            "equity": self.equity,
            "session_pnl": self.session_pnl,
            "last_decision": self.last_decision,
            "last_decision_reason": self.last_decision_reason,
            "pending": self.pending,
            "processed_candles": self.processed_candles,
            "details": self.details,
        }


class PaperTradingEngine:
    """The paper pipeline: feed → strategy → risk → simulated execution."""

    def __init__(
        self,
        database: Database,
        adapter: FakeExchangeAdapter,
        *,
        product_id: str = "BTC-USD",
        timeframe: str = "1h",
        config: EmaRsiConfig | None = None,
        assumptions: FeeAssumptions | None = None,
        starting_quote: Decimal = Decimal("1000"),
        position_size_quote: Decimal = Decimal("500"),
        poll_seconds: float = 2.0,
        stale_after_seconds: float = 300.0,
        status: PaperStatus | None = None,
    ) -> None:
        self._db = database
        self._adapter = adapter
        self.product_id = product_id
        self.timeframe = timeframe
        self.granularity = granularity_for_timeframe(timeframe)
        self.bucket_seconds = granularity_seconds(self.granularity)
        self.config = config or EmaRsiConfig(product_id=product_id, timeframe=timeframe)
        self.assumptions = assumptions or FeeAssumptions()
        self.position_size_quote = position_size_quote
        self.poll_seconds = poll_seconds
        self.stale_after_seconds = stale_after_seconds
        self.status = status or PaperStatus()

        self.strategy = get_strategy(STRATEGY_NAME)
        self.risk = RiskManager()
        self.account = PaperAccount(database)
        self.controller = TradingController(database)
        self.candles = CandleRepository(database)
        self.positions = PositionRepository(database)
        self.intents = IntentService(database)
        self.ledger = DailyLedger(database)

        self._last_processed: datetime | None = None
        self._window: list[Candle] = []
        self._pending: SignalType | None = None
        self._pending_intent_id: str | None = None
        self._pending_base: Decimal = Decimal(0)
        self._stop_requested = False

    # -- lifecycle ---------------------------------------------------

    async def run(self) -> None:
        self._recover()
        self.account.ensure_session()
        self.status.running = True
        try:
            while not self._stop_requested:
                await asyncio.sleep(self.poll_seconds)
                try:
                    self.process_once()
                except Exception as exc:  # noqa: BLE001 - paper loop survives
                    self.status.details["last_error"] = str(exc)
        finally:
            self.status.running = False

    def stop(self) -> None:
        self._stop_requested = True

    def _recover(self) -> None:
        """Restart recovery (documented policy): cancel in-flight intents
        and adopt persisted positions/cash. Persisted state already
        reflects every applied fill."""
        for intent in self.intents.intents().list_unresolved():
            if intent.state == "open":
                continue
            try:
                self.intents.intents().mark(intent.client_order_id, "cancel_pending")
                self.intents.intents().mark(intent.client_order_id, "canceled")
            except Exception:  # noqa: BLE001 - best effort recovery
                pass
        self._pending = None
        self._pending_intent_id = None

    # -- processing --------------------------------------------------

    def process_once(self, *, now: datetime | None = None) -> str | None:
        """Process any newly completed candle. Returns a description."""
        moment = now or datetime.now(UTC)
        latest = self.candles.latest_complete_start(self.product_id, self.granularity)
        if latest is None:
            return None
        if self._last_processed is None:
            # First run: seed the window with history. The newest candle is
            # processed as a live candle on the next call.
            self._seed_window(latest)
            self.status.processed_candles = len(self._window)
            return "seeded"
        if latest <= self._last_processed:
            return None

        fresh = self.candles.get_range(
            self.product_id,
            self.granularity,
            self._last_processed + timedelta(seconds=self.bucket_seconds),
            latest + timedelta(seconds=1),
        )
        actions: list[str] = []
        for candle in fresh:
            action = self._process_candle(candle, moment)
            if action:
                actions.append(action)
        self._last_processed = latest
        self.status.processed_candles += len(fresh)
        return "; ".join(actions) if actions else None

    def _seed_window(self, latest: datetime) -> None:
        required = self.strategy.required_history(self.config)
        window_start = latest - timedelta(seconds=(required - 1) * self.bucket_seconds)
        self._window = self.candles.get_range(
            self.product_id, self.granularity, window_start, latest + timedelta(seconds=1)
        )
        # The newest candle is processed as a LIVE candle on the next call —
        # seeding must not consume the decision candle silently.
        self._last_processed = latest - timedelta(seconds=self.bucket_seconds)

    def _process_candle(self, candle: Candle, moment: datetime) -> str | None:
        action: str | None = None
        self._window = [c for c in self._window if c.start_time < candle.start_time]
        self._window.append(candle)

        # 1) execute pending orders at this candle's open (next-open model,
        #    consistent with the backtester's fee/slippage assumptions).
        if self._pending == SignalType.BUY and self._position_size() == 0:
            action = self._fill_entry(candle, moment)
        elif self._pending == SignalType.SELL and self._position_size() > 0:
            action = self._fill_exit(candle, moment)
        self._pending = None
        self._pending_intent_id = None

        # 2) paper equity snapshot (mark to close).
        equity = self.account.cash() + self._position_size() * candle.close
        mark_time = candle.start_time + timedelta(seconds=self.bucket_seconds)
        self.account.record_equity(equity, now=mark_time)
        self.ledger.record_equity(equity, now=mark_time)

        # 3) decide on the completed candle.
        decision = self.strategy.evaluate(
            list(self._window), self.config, position=self._position()
        )
        self.status.last_decision = decision.signal.value
        self.status.last_decision_reason = decision.reason_code

        # 4) act on the decision (fills happen at the NEXT open).
        if decision.signal == SignalType.BUY and self._position_size() == 0:
            action = action or ""
            if self.controller.entries_allowed():
                gated = self._risk_gate_entry(candle, decision, moment)
                if gated:
                    self._pending = SignalType.BUY
                    action = f"buy pending at {candle.start_time.strftime('%H:%M')}+1 open"
            elif not action:
                action = "entry suppressed (entries paused)"
        elif decision.signal == SignalType.SELL and self._position_size() > 0:
            # Protective management continues while entries are paused.
            # Exits are gated only by the kill switch (not entry caps).
            exit_context = RiskContext(
                product_id=self.product_id,
                quote_notional=self._position_size() * candle.close,
                base_size=self._position_size(),
                price=candle.close,
                product=self._adapter.get_product(self.product_id),
                current_position_quote=self._position_size() * candle.close,
                total_exposure_quote=self._position_size() * candle.close,
                open_orders_count=0,
                open_positions_count=1,
                cash_available=self.account.cash(),
                daily_drawdown_pct=self.ledger.drawdown_pct(
                    self.account.cash() + self._position_size() * candle.close, now=moment
                ),
                stale_data=False,
                cooldown_active=False,
                kill_switch_active=self.controller.kill_switch_active(),
            )
            exit_gate = self.risk.check_exit(exit_context)
            exit_intent, _ = self.intents.get_or_create_entry(
                product_id=self.product_id,
                side="sell",
                bucket_key=f"exit-{candle.start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                config_hash=self.config.config_hash(),
                base_size=self._position_size(),
                price=candle.close,
                order_kind="market",
            )
            if not exit_gate.allowed:
                self.intents.intents().mark(
                    exit_intent.client_order_id, "rejected", risk_reason=exit_gate.message
                )
                self.status.details["last_risk_rejection"] = exit_gate.message
                return action
            self.intents.intents().mark(exit_intent.client_order_id, "risk_approved")
            self._pending = SignalType.SELL
            self._pending_intent_id = exit_intent.client_order_id
            self._pending_base = self._position_size()
            action = f"sell pending at {candle.start_time.strftime('%H:%M')}+1 open"
        return action

    def _fill_entry(self, candle: Candle, moment: datetime) -> str:
        intent_id = self._pending_intent_id
        assert intent_id is not None
        fill_price = self.assumptions.entry_fill(candle.open)
        result = self._adapter.create_order(
            self._request(intent_id, candle, fill_price, self._pending_base)
        )
        assert result.accepted and result.exchange_order_id is not None
        self.intents.exchange_orders().record(
            client_order_id=intent_id,
            exchange_order_id=result.exchange_order_id,
            product_id=self.product_id,
            side="buy",
            status="OPEN",
        )
        # Walk the intent through its legal transitions at fill time.
        self.intents.intents().mark(intent_id, SUBMITTING)
        self.intents.intents().mark(intent_id, ACKNOWLEDGED)
        self.intents.intents().mark(intent_id, OPEN)
        fill = self._adapter.simulate_fill(intent_id, price=fill_price)
        assert fill is not None
        apply_fill_idempotent(self._db, fill)
        self.intents.intents().mark(intent_id, FILLED)
        notional = self._pending_base * fill_price
        self.account.apply_entry(notional, fill.commission, now=candle.start_time)
        return f"entry filled at {fill_price} (+fees)"

    def _fill_exit(self, candle: Candle, moment: datetime) -> str:
        intent_id = self._pending_intent_id
        assert intent_id is not None
        fill_price = self.assumptions.exit_fill(candle.open)
        result = self._adapter.create_order(
            self._request(intent_id, candle, fill_price, self._position_size(), side="sell")
        )
        assert result.accepted and result.exchange_order_id is not None
        self.intents.exchange_orders().record(
            client_order_id=intent_id,
            exchange_order_id=result.exchange_order_id,
            product_id=self.product_id,
            side="sell",
            status="OPEN",
        )
        self.intents.intents().mark(intent_id, SUBMITTING)
        self.intents.intents().mark(intent_id, ACKNOWLEDGED)
        self.intents.intents().mark(intent_id, OPEN)
        fill = self._adapter.simulate_fill(intent_id, price=fill_price)
        assert fill is not None
        # Capture the size BEFORE applying: the fill zeroes the position.
        exit_size = fill.size
        apply_fill_idempotent(self._db, fill)
        self.intents.intents().mark(intent_id, FILLED)
        proceeds = exit_size * fill_price
        self.account.apply_exit(proceeds, fill.commission, now=candle.start_time)
        return f"exit filled at {fill_price} (+fees)"

    def _request(
        self,
        intent_id: str,
        candle: Candle,
        price: Decimal,
        size: Decimal,
        *,
        side: str = "buy",
    ) -> OrderRequest:
        return OrderRequest(
            client_order_id=intent_id,
            product_id=self.product_id,
            side=OrderSide(side),
            base_size=size,
            limit_price=price,
        )

    # -- decision action ----------------------------------------------

    def _risk_gate_entry(
        self, candle: Candle, decision: object, moment: datetime
    ) -> bool:
        """Run the mandatory risk gate; persist the durable intent."""
        price = candle.close
        product = self._adapter.get_product(self.product_id)
        sized = size_entry(self.position_size_quote, price, product)
        intent, _ = self.intents.get_or_create_entry(
            product_id=self.product_id,
            side="buy",
            bucket_key=candle.start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            config_hash=self.config.config_hash(),
            base_size=sized.base_size,
            price=price,
        )
        self._pending_intent_id = intent.client_order_id
        position = self.positions.get(self.product_id)
        position_quote = (position.size or Decimal(0)) * price if position else Decimal(0)
        exposure = sum(
            ((p.size or Decimal(0)) * price for p in self.positions.open_positions()),
            start=Decimal(0),
        )
        stale = self._is_stale(candle, moment)
        context = RiskContext(
            product_id=self.product_id,
            quote_notional=self.position_size_quote,
            base_size=sized.base_size,
            price=price,
            product=self._adapter.get_product(self.product_id),
            current_position_quote=position_quote,
            total_exposure_quote=exposure,
            open_orders_count=0,
            open_positions_count=len(self.positions.open_positions()),
            cash_available=self.account.cash(),
            daily_drawdown_pct=self.ledger.drawdown_pct(self.account.cash() + exposure, now=moment),
            stale_data=stale,
            cooldown_active=False,
            kill_switch_active=self.controller.kill_switch_active(),
        )
        gate = self.risk.check_entry(context)
        next_state = "risk_approved" if gate.allowed else "rejected"
        self.intents.intents().mark(intent.client_order_id, next_state)
        if not gate.allowed:
            self._pending_intent_id = None
            self.status.details["last_risk_rejection"] = gate.message
            return False
        self._pending_base = sized.base_size
        return True

    def _is_stale(self, candle: Candle, moment: datetime) -> bool:
        bucket_end = candle.start_time + timedelta(seconds=self.bucket_seconds)
        age = (moment - bucket_end).total_seconds()
        return age > self.stale_after_seconds

    def _position_size(self) -> Decimal:
        position = self.positions.get(self.product_id)
        return (position.size or Decimal(0)) if position else Decimal(0)

    def _position(self) -> StrategyPosition:
        position = self.positions.get(self.product_id)
        if position is None or (position.size or Decimal(0)) == 0:
            return FLAT_POSITION
        return StrategyPosition(side="long", size=position.size)
