"""The backtesting engine: candle-level replay with conservative fills.

Candle-resolution assumptions (architecture.md §11, documented on every
result):

- a decision made on candle *t*'s close executes at candle *t+1*'s open,
  adjusted by the assumed slippage — the decision window ends at *t*, so
  no future candle value can leak into a decision;
- there is no intrabar sequencing: fills happen at next-open only;
- fees are charged on entry and exit, in quote currency;
- base sizes round down to the product increment;
- an open position at end-of-data is force-closed at the final close
  (labeled) so every run ends fully in cash.

All arithmetic uses Decimal; results are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.market_data.candles import Candle
from trendbot.strategies.base import Strategy
from trendbot.strategies.config import EmaRsiConfig
from trendbot.strategies.decisions import FLAT_POSITION, SignalType, StrategyPosition

END_OF_DATA = "end_of_data"


class _OpenEntry(TypedDict):
    """The in-flight simulated position awaiting its exit fill."""

    time: datetime
    price: Decimal
    notional: Decimal
    fee: Decimal


@dataclass(frozen=True)
class TradeRecord:
    """One completed round trip in the simulated ledger."""

    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    base_size: Decimal
    entry_notional: Decimal
    fee_entry: Decimal
    fee_exit: Decimal
    pnl_quote: Decimal
    pnl_pct: Decimal
    note: str = ""


@dataclass(frozen=True)
class BacktestMetrics:
    net_return_pct: Decimal
    gross_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    win_rate_pct: Decimal | None
    avg_win_quote: Decimal | None
    avg_loss_quote: Decimal | None
    profit_factor: Decimal | None
    exposure_pct: Decimal
    total_fees_quote: Decimal
    benchmark_return_pct: Decimal
    start: datetime
    end: datetime


@dataclass(frozen=True)
class BacktestResult:
    """Everything one simulation run produced."""

    candles_from: datetime
    candles_to: datetime
    initial_quote: Decimal
    final_equity: Decimal
    metrics: BacktestMetrics
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)

    def summary_dict(self) -> dict[str, object]:
        metrics = self.metrics
        return {
            "candles_from": self.candles_from.isoformat(),
            "candles_to": self.candles_to.isoformat(),
            "initial_quote": str(self.initial_quote),
            "final_equity": str(self.final_equity),
            "net_return_pct": str(metrics.net_return_pct),
            "gross_return_pct": str(metrics.gross_return_pct),
            "max_drawdown_pct": str(metrics.max_drawdown_pct),
            "trade_count": metrics.trade_count,
            "win_rate_pct": None if metrics.win_rate_pct is None else str(metrics.win_rate_pct),
            "avg_win_quote": (
                None if metrics.avg_win_quote is None else str(metrics.avg_win_quote)
            ),
            "avg_loss_quote": (
                None if metrics.avg_loss_quote is None else str(metrics.avg_loss_quote)
            ),
            "profit_factor": None if metrics.profit_factor is None else str(metrics.profit_factor),
            "exposure_pct": str(metrics.exposure_pct),
            "total_fees_quote": str(metrics.total_fees_quote),
            "benchmark_return_pct": str(metrics.benchmark_return_pct),
            "trades": [
                {
                    "entry_time": trade.entry_time.isoformat(),
                    "exit_time": trade.exit_time.isoformat(),
                    "entry_price": str(trade.entry_price),
                    "exit_price": str(trade.exit_price),
                    "base_size": str(trade.base_size),
                    "fee_entry": str(trade.fee_entry),
                    "fee_exit": str(trade.fee_exit),
                    "pnl_quote": str(trade.pnl_quote),
                    "pnl_pct": str(trade.pnl_pct),
                    "note": trade.note,
                }
                for trade in self.trades
            ],
        }


class BacktestEngine:
    """Replays a strategy over chronological candles with simulated fills."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        assumptions: FeeAssumptions,
        initial_quote: Decimal,
        position_size_quote: Decimal,
    ) -> None:
        self.strategy = strategy
        self.assumptions = assumptions
        self.initial_quote = initial_quote
        self.position_size_quote = position_size_quote

    def run(self, candles: list[Candle], config: EmaRsiConfig) -> BacktestResult:
        if len(candles) < 2:
            raise ValueError("A backtest needs at least 2 candles.")
        if any(not candle.is_complete for candle in candles):
            raise ValueError("Backtests may only run on completed candles.")
        config.require_valid()

        fee_rate = self.assumptions.fee_rate
        cash = self.initial_quote
        base_held = Decimal(0)
        entry: _OpenEntry | None = None
        pending: SignalType | None = None
        trades: list[TradeRecord] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        candles_in_market = 0

        for index, candle in enumerate(candles):
            if pending == SignalType.BUY and base_held == 0:
                notional = min(self.position_size_quote, cash)
                fee = notional * fee_rate
                # An entry must be fully affordable: notional + fee in cash.
                if notional > 0 and cash >= notional + fee:
                    fill = self.assumptions.entry_fill(candle.open)
                    base_held = self.assumptions.round_base_down(notional / fill)
                    cash -= notional + fee
                    entry = {
                        "time": candle.start_time,
                        "price": fill,
                        "notional": notional,
                        "fee": fee,
                    }
            elif pending == SignalType.SELL and base_held > 0:
                # A held position always has an entry record (invariant above).
                assert entry is not None
                fill = self.assumptions.exit_fill(candle.open)
                trade, cash, base_held = self._close_position(
                    cash, base_held, entry, fill, candle.start_time, note=""
                )
                trades.append(trade)
                entry = None
            pending = None

            if base_held > 0:
                candles_in_market += 1
            equity_curve.append((candle.start_time, cash + base_held * candle.close))

            if index + 1 < len(candles):
                window = candles[: index + 1]
                if len(window) >= self.strategy.required_history(config):
                    position = StrategyPosition(
                        side="long" if base_held > 0 else "flat", size=base_held
                    )
                    decision = self.strategy.evaluate(
                        window, config, position=position or FLAT_POSITION
                    )
                    if decision.signal == SignalType.BUY and base_held == 0:
                        pending = SignalType.BUY
                    elif decision.signal == SignalType.SELL and base_held > 0:
                        pending = SignalType.SELL

        if base_held > 0 and entry is not None:
            last = candles[-1]
            fill = self.assumptions.exit_fill(last.close)
            trade, cash, base_held = self._close_position(
                cash, base_held, entry, fill, last.start_time, note=END_OF_DATA
            )
            trades.append(trade)
            equity_curve[-1] = (last.start_time, cash)

        return BacktestResult(
            candles_from=candles[0].start_time,
            candles_to=candles[-1].start_time,
            initial_quote=self.initial_quote,
            final_equity=equity_curve[-1][1],
            metrics=self._metrics(candles, trades, equity_curve, candles_in_market),
            trades=trades,
            equity_curve=equity_curve,
        )

    def _close_position(
        self,
        cash: Decimal,
        base_held: Decimal,
        entry: _OpenEntry,
        fill: Decimal,
        exit_time: datetime,
        *,
        note: str,
    ) -> tuple[TradeRecord, Decimal, Decimal]:
        proceeds = base_held * fill
        fee_exit = proceeds * self.assumptions.fee_rate
        cash += proceeds - fee_exit
        entry_notional = entry["notional"]
        fee_entry = entry["fee"]
        pnl = proceeds - fee_exit - entry_notional - fee_entry
        pnl_pct = pnl / entry_notional * Decimal(100) if entry_notional else Decimal(0)
        trade = TradeRecord(
            entry_time=entry["time"],
            exit_time=exit_time,
            entry_price=entry["price"],
            exit_price=fill,
            base_size=base_held,
            entry_notional=entry_notional,
            fee_entry=fee_entry,
            fee_exit=fee_exit,
            pnl_quote=pnl,
            pnl_pct=pnl_pct,
            note=note,
        )
        return trade, cash, Decimal(0)

    def _metrics(
        self,
        candles: list[Candle],
        trades: list[TradeRecord],
        equity_curve: list[tuple[datetime, Decimal]],
        candles_in_market: int,
    ) -> BacktestMetrics:
        final_equity = equity_curve[-1][1]
        fees_total = sum(
            (trade.fee_entry + trade.fee_exit for trade in trades), start=Decimal(0)
        )
        net_return = (final_equity / self.initial_quote - Decimal(1)) * Decimal(100)
        gross_return = (
            (final_equity + fees_total) / self.initial_quote - Decimal(1)
        ) * Decimal(100)

        peak = equity_curve[0][1] if equity_curve else self.initial_quote
        max_drawdown = Decimal(0)
        for _, equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                drawdown = (peak - equity) / peak * Decimal(100)
                max_drawdown = max(max_drawdown, drawdown)

        wins = [trade.pnl_quote for trade in trades if trade.pnl_quote > 0]
        losses = [trade.pnl_quote for trade in trades if trade.pnl_quote <= 0]
        gross_wins = sum(wins, start=Decimal(0))
        gross_losses = abs(sum(losses, start=Decimal(0)))
        win_rate = (
            Decimal(len(wins)) / Decimal(len(trades)) * Decimal(100)
            if trades
            else None
        )
        profit_factor = (
            None
            if not losses and not wins
            else (None if not losses else gross_wins / gross_losses)
        )

        first_close = candles[0].close
        last_close = candles[-1].close
        benchmark = (last_close / first_close - Decimal(1)) * Decimal(100)

        total = len(candles)
        exposure = (
            Decimal(candles_in_market) / Decimal(total) * Decimal(100)
            if total
            else Decimal(0)
        )
        return BacktestMetrics(
            net_return_pct=net_return,
            gross_return_pct=gross_return,
            max_drawdown_pct=max_drawdown,
            trade_count=len(trades),
            win_rate_pct=win_rate,
            avg_win_quote=(gross_wins / Decimal(len(wins)) if wins else None),
            avg_loss_quote=(
                sum(losses, start=Decimal(0)) / Decimal(len(losses)) if losses else None
            ),
            profit_factor=profit_factor,
            exposure_pct=exposure,
            total_fees_quote=fees_total,
            benchmark_return_pct=benchmark,
            start=candles[0].start_time,
            end=candles[-1].start_time,
        )
