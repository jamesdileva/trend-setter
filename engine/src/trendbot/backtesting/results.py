"""Out-of-sample splitting and results export (roadmap Sprint 7 tasks 7-8)."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from trendbot.backtesting.engine import BacktestResult


def split_in_sample_out_of_sample(
    candles: list, in_sample_fraction: float = 0.7
) -> tuple[list, list]:
    """Split chronologically: tuning (in-sample) first, validation second.

    The two windows never overlap. A fraction outside (0, 1) is rejected.
    """
    if not 0 < in_sample_fraction < 1:
        raise ValueError("The in-sample fraction must be between 0 and 1 (exclusive).")
    if len(candles) < 2:
        raise ValueError("Splitting needs at least 2 candles.")
    cut = max(1, int(len(candles) * in_sample_fraction))
    if cut >= len(candles):
        raise ValueError("The in-sample window must leave candles for out-of-sample validation.")
    return candles[:cut], candles[cut:]


def export_results_json(result: BacktestResult, path: Path) -> Path:
    """Write the full result (summary, trades, equity curve) as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.summary_dict(),
        "equity_curve": [
            {"time": moment.isoformat(), "equity": str(equity)}
            for moment, equity in result.equity_curve
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def export_trades_csv(result: BacktestResult, path: Path) -> Path:
    """Write the trade ledger as CSV (Excel-friendly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "base_size",
        "entry_notional",
        "fee_entry",
        "fee_exit",
        "pnl_quote",
        "pnl_pct",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for trade in result.trades:
            data = asdict(trade)
            writer.writerow({column: str(data[column]) for column in columns})
    return path
