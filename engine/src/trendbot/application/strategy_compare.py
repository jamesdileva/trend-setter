"""Strategy comparison: rank candidate strategies on stored history.

Discipline rules (Sprint 16, and why they exist):

- SMALL grids only. Every extra parameter combination multiplies the chance
  that the "winner" is luck, not skill — the best-of-N overfitting problem.
- Rankings use the OUT-OF-SAMPLE split (the final 30% of the window the
  in-sample split holds back). In-sample results are shown for context only.
- A buy-and-hold benchmark row is always included: a strategy that cannot
  beat doing nothing is not worth running.
- Low out-of-sample trade counts are marked weak evidence — a ranking built
  on two trades is a coin flip with extra steps.
- Nothing here changes the active strategy; choosing stays a human decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from trendbot.application.backtest_service import run_backtest_over_store
from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.database.repositories import CandleRepository
from trendbot.database.session import Database
from trendbot.market_data.candles import Candle
from trendbot.market_data.granularity import granularity_for_timeframe
from trendbot.strategies.config import DonchianConfig, EmaRsiConfig, StrategyConfig
from trendbot.strategies.registry import get_strategy

# Deliberately small grids: a handful of sensible candidates per family.
# This is candidate generation, not parameter optimization.
EMA_RSI_GRID: tuple[dict[str, int | float], ...] = (
    {"fast_ema_period": 20, "slow_ema_period": 50, "rsi_entry_ceiling": 70.0},
    {"fast_ema_period": 10, "slow_ema_period": 50, "rsi_entry_ceiling": 70.0},
    {"fast_ema_period": 20, "slow_ema_period": 50, "rsi_entry_ceiling": 80.0},
    {"fast_ema_period": 10, "slow_ema_period": 30, "rsi_entry_ceiling": 70.0},
    {"fast_ema_period": 20, "slow_ema_period": 100, "rsi_entry_ceiling": 70.0},
    {"fast_ema_period": 50, "slow_ema_period": 200, "rsi_entry_ceiling": 70.0},
)
DONCHIAN_GRID: tuple[dict[str, int | float], ...] = (
    {"entry_lookback": 20, "exit_lookback": 10},
    {"entry_lookback": 55, "exit_lookback": 20},
    {"entry_lookback": 10, "exit_lookback": 5},
)

STRATEGY_GRIDS: dict[str, tuple[dict[str, int | float], ...]] = {
    "ema_rsi_baseline": EMA_RSI_GRID,
    "donchian_breakout": DONCHIAN_GRID,
}

CAVEATS: tuple[str, ...] = (
    "Ranked by how each strategy did on the final 30% of the window — data "
    "the strategy parameters were not chosen on.",
    "Picking the best of several backtests overstates likely future "
    "performance. Treat the ranking as candidates to paper-trade, not "
    "promises.",
    "Past performance does not guarantee future results.",
)


def _params_label(params: dict[str, int | float]) -> str:
    return ", ".join(f"{key.replace('_', ' ')}={value}" for key, value in params.items())


def _build_config(
    strategy_name: str, product_id: str, timeframe: str, params: dict[str, int | float]
) -> StrategyConfig:
    if strategy_name == "ema_rsi_baseline":
        return EmaRsiConfig(
            product_id=product_id,
            timeframe=timeframe,
            fast_ema_period=int(params["fast_ema_period"]),
            slow_ema_period=int(params["slow_ema_period"]),
            rsi_entry_ceiling=float(params["rsi_entry_ceiling"]),
        )
    return DonchianConfig(
        product_id=product_id,
        timeframe=timeframe,
        entry_lookback=int(params["entry_lookback"]),
        exit_lookback=int(params["exit_lookback"]),
    )


def buy_and_hold_metrics(
    candles: list[Candle], assumptions: FeeAssumptions
) -> dict[str, object]:
    """Benchmark: buy the first open, sell the last close, pay both fees."""
    assert candles
    fee_rate = Decimal(str(assumptions.fee_bps)) / Decimal(10_000)
    entry = assumptions.entry_fill(candles[0].open)
    exit_price = assumptions.exit_fill(candles[-1].close)
    base = Decimal("1")  # normalized: return is fee-adjusted percentage
    spent = base * entry * (Decimal(1) + fee_rate)
    received = base * exit_price * (Decimal(1) - fee_rate)
    net_return_pct = (received / spent - Decimal(1)) * Decimal(100)

    # Peak-to-trough drawdown of the close series.
    peak = candles[0].close
    max_drawdown = Decimal(0)
    for candle in candles:
        peak = max(peak, candle.close)
        if peak > 0:
            drawdown = (peak - candle.close) / peak * Decimal(100)
            max_drawdown = max(max_drawdown, drawdown)

    return {
        "strategy_name": "buy_and_hold_benchmark",
        "params": "buy first open, sell last close",
        "full_net_return_pct": str(net_return_pct),
        "max_drawdown_pct": str(max_drawdown),
        "trade_count": 1,
    }


@dataclass(frozen=True)
class CompareRow:
    strategy_name: str
    params_label: str
    full_net_return_pct: str
    oos_net_return_pct: str
    oos_max_drawdown_pct: str | None
    oos_trade_count: int
    oos_verdict: str

    def as_dict(self) -> dict[str, object]:
        return {
            "strategy_name": self.strategy_name,
            "params": self.params_label,
            "full_net_return_pct": self.full_net_return_pct,
            "oos_net_return_pct": self.oos_net_return_pct,
            "oos_max_drawdown_pct": self.oos_max_drawdown_pct,
            "oos_trade_count": self.oos_trade_count,
            "oos_verdict": self.oos_verdict,
        }


def compare_strategies(
    database: Database,
    *,
    product_id: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    in_sample_fraction: float = 0.7,
) -> dict[str, object]:
    """Run every registered strategy family over a small grid and rank by OOS."""
    candle_repo = CandleRepository(database)
    granularity = granularity_for_timeframe(timeframe)
    end = end or datetime.now(UTC)
    latest = candle_repo.latest_start(product_id, granularity)
    if latest is not None:
        end = min(end, latest + timedelta(minutes=1))
    stored_first = candle_repo.oldest_start(product_id, granularity)
    if stored_first is None:
        from trendbot.application.backtest_service import InsufficientDataError

        raise InsufficientDataError(
            f"No stored candles for {product_id} at {timeframe}. "
            "Import history first."
        )
    start = start or stored_first

    assumptions = FeeAssumptions()
    rows: list[CompareRow] = []

    for strategy_name, grid in STRATEGY_GRIDS.items():
        get_strategy(strategy_name)  # validates registration before any run
        for params in grid:
            config = _build_config(strategy_name, product_id, timeframe, params)
            config.require_valid()
            result = run_backtest_over_store(
                database,
                product_id=product_id,
                timeframe=timeframe,
                start=start,
                end=end,
                config=config,
                assumptions=assumptions,
                in_sample_fraction=in_sample_fraction,
                strategy_name=strategy_name,
                persist=False,
            )
            result_body = cast(dict[str, object], result["result"])
            oos = cast(
                dict[str, object],
                cast(dict[str, object], result["out_of_sample"])["out_of_sample"],
            )
            oos_trades = int(cast("int", oos["trade_count"]))
            if oos_trades >= 10:
                verdict = "meaningful sample"
            elif oos_trades >= 3:
                verdict = "few trades — weak evidence"
            else:
                verdict = "too few trades to judge"
            rows.append(
                CompareRow(
                    strategy_name=strategy_name,
                    params_label=_params_label(params),
                    full_net_return_pct=str(result_body["net_return_pct"]),
                    oos_net_return_pct=str(oos["net_return_pct"]),
                    oos_max_drawdown_pct=str(result_body["max_drawdown_pct"]),
                    oos_trade_count=oos_trades,
                    oos_verdict=verdict,
                )
            )

    # OOS net return, descending; ties broken by full-window return.
    ranked = sorted(
        rows,
        key=lambda row: (Decimal(row.oos_net_return_pct), Decimal(row.full_net_return_pct)),
        reverse=True,
    )

    window_candles = candle_repo.get_range(product_id, granularity, start, end)
    complete_window = [candle for candle in window_candles if candle.is_complete]
    benchmark = (
        buy_and_hold_metrics(complete_window, assumptions)
        if len(complete_window) > 1
        else None
    )

    return {
        "status": "comparison_complete",
        "warning": (
            "Backtests are estimates with assumptions — not predictions. "
            "Rankings are candidates for paper trading; nothing is applied "
            "automatically."
        ),
        "product_id": product_id,
        "timeframe": timeframe,
        "window": {
            "start": complete_window[0].start_time.isoformat() if complete_window else None,
            "end": complete_window[-1].start_time.isoformat() if complete_window else None,
            "candles": len(complete_window),
            "in_sample_fraction": in_sample_fraction,
        },
        "ranking": [row.as_dict() for row in ranked],
        "benchmark": benchmark,
        "caveats": list(CAVEATS),
    }
