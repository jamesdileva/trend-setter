"""Backtest service: run a labeled simulation over stored candles (Sprint 7).

Orchestrates candle loading, the backtest engine, the out-of-sample
split, and persistence. Every result is explicitly labeled a historical
simulation with its assumptions and limitations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.backtesting.engine import BacktestEngine
from trendbot.backtesting.results import split_in_sample_out_of_sample
from trendbot.database.repositories import (
    BacktestRepository,
    CandleRepository,
    StrategyConfigRepository,
)
from trendbot.database.session import Database
from trendbot.market_data.granularity import granularity_for_timeframe
from trendbot.strategies.config import STRATEGY_NAME, StrategyConfig
from trendbot.strategies.registry import get_strategy

SIMULATION_WARNING = (
    "HISTORICAL SIMULATION — not paper trading, not live. Fills are "
    "next-open only with placeholder fee/slippage assumptions; intrabar "
    "sequencing cannot be modeled from candles. Backtests are estimates, "
    "not guarantees."
)


class InsufficientDataError(RuntimeError):
    """Raised when the stored candle range cannot support a backtest."""


def run_backtest_over_store(
    database: Database,
    *,
    product_id: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    config: StrategyConfig,
    assumptions: FeeAssumptions | None = None,
    initial_quote: Decimal = Decimal("1000"),
    position_size_quote: Decimal = Decimal("500"),
    in_sample_fraction: float = 0.7,
    strategy_name: str = STRATEGY_NAME,
    persist: bool = True,
) -> dict[str, object]:
    """Run one simulation over the stored candle range.

    ``persist=False`` (used by comparison sweeps) skips the backtest_runs
    table so a multi-run sweep does not flood the runs history.
    """
    config.require_valid()
    assumptions = assumptions or FeeAssumptions()
    strategy = get_strategy(strategy_name)
    granularity = granularity_for_timeframe(timeframe)

    candle_repo = CandleRepository(database)
    end = end or datetime.now(UTC)
    start = start or (end - timedelta(days=30))
    # Request dates may be plain ISO dates; treat them as UTC midnight.
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    candles = candle_repo.get_range(product_id, granularity, start, end)

    required = strategy.required_history(config) + 2
    if len(candles) < required:
        raise InsufficientDataError(
            f"Only {len(candles)} stored candles for {product_id} at {timeframe}; "
            f"a backtest needs at least {required}. Import more history first."
        )

    engine = BacktestEngine(
        strategy=strategy,
        assumptions=assumptions,
        initial_quote=initial_quote,
        position_size_quote=position_size_quote,
    )
    result = engine.run(candles, config)

    in_sample, out_of_sample = split_in_sample_out_of_sample(
        candles, in_sample_fraction=in_sample_fraction
    )
    in_result = engine.run(in_sample, config)
    out_result = engine.run(out_of_sample, config)

    repo = BacktestRepository(database)
    run_id: int | None = None
    config_row = None
    if persist:
        config_row = StrategyConfigRepository(database).get_or_create(
            name=strategy_name, config_json=config.to_dict(), config_hash=config.config_hash()
        )
        run_id = repo.record_run(
        strategy_config_id=config_row.id,
        product_id=product_id,
        timeframe=timeframe,
        start_time=result.candles_from,
        end_time=result.candles_to,
        assumptions=assumptions.as_dict(),
        metrics={
            "net_return_pct": str(result.metrics.net_return_pct),
            "gross_return_pct": str(result.metrics.gross_return_pct),
            "max_drawdown_pct": str(result.metrics.max_drawdown_pct),
            "trade_count": result.metrics.trade_count,
            "win_rate_pct": (
                None if result.metrics.win_rate_pct is None else str(result.metrics.win_rate_pct)
            ),
            "in_sample_net_return_pct": str(in_result.metrics.net_return_pct),
            "out_of_sample_net_return_pct": str(out_result.metrics.net_return_pct),
            "in_sample_trades": in_result.metrics.trade_count,
            "out_of_sample_trades": out_result.metrics.trade_count,
            "in_sample_fraction": in_sample_fraction,
        },
    )
    if persist and run_id is not None:
        for trade in result.trades:
            repo.record_trade(run_id, trade)

    return {
        "status": "simulation_complete",
        "warning": SIMULATION_WARNING,
        "run_id": run_id,
        "product_id": product_id,
        "timeframe": timeframe,
        "config_hash": config.config_hash(),
        "assumptions": assumptions.as_dict(),
        "result": result.summary_dict(),
        "out_of_sample": {
            "in_sample_fraction": in_sample_fraction,
            "in_sample": {
                "candles": len(in_sample),
                "net_return_pct": str(in_result.metrics.net_return_pct),
                "trade_count": in_result.metrics.trade_count,
            },
            "out_of_sample": {
                "candles": len(out_of_sample),
                "net_return_pct": str(out_result.metrics.net_return_pct),
                "trade_count": out_result.metrics.trade_count,
            },
        },
    }
