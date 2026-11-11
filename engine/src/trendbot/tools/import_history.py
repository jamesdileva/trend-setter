"""Operator tool: import historical candles for a product/timeframe.

Developer/operator convenience while the backtesting UI does not exist
yet (roadmap Sprint 4 task 4; the nontechnical-user import flow arrives
with the backtest sprint). Uses the verified public endpoint family when
no credential is connected, and authenticated requests when one is.

Usage (from the repository root, venv active):

  python -m trendbot.tools.import_history --product BTC-USD --timeframe 1h --days 30
  python -m trendbot.tools.import_history --timeframe 1h --start 2026-01-01 --end 2026-02-01
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

from trendbot.application.coinbase_connection import (
    SECRET_KEY,
    CoinbaseConnectionService,
    default_client_factory,
)
from trendbot.config.paths import default_data_dir, ensure_data_dir
from trendbot.database import Database, upgrade_to_head
from trendbot.exchange.coinbase_rest import CoinbaseRestClient, fetch_public_candles
from trendbot.market_data.granularity import granularity_for_timeframe
from trendbot.market_data.importer import CandleImporter, CandlePageLike, ImportSummary
from trendbot.security.secret_store import default_secret_store

PRODUCTS = ("BTC-USD", "ETH-USD")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")

FetchPage = Callable[[datetime, datetime], CandlePageLike]


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def resolve_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start or args.end:
        if not (args.start and args.end):
            _fail("--start and --end must be given together (ISO dates, e.g. 2026-01-01).")
        return _parse_date(args.start), _parse_date(args.end)
    end = datetime.now(UTC)
    return end - timedelta(days=args.days), end


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def _build_fetch(
    database: Database, product_id: str, timeframe: str
) -> FetchPage:
    """Authenticated fetch when a credential is connected; public otherwise."""
    secrets = default_secret_store()
    service = CoinbaseConnectionService(database, secrets, default_client_factory())
    state = service.status()
    granularity = granularity_for_timeframe(timeframe)
    if not state.connected:
        print(
            "No connected Coinbase credential — using the public (unauthenticated) data endpoints."
        )

        def public_fetch(w_start: datetime, w_end: datetime) -> CandlePageLike:
            return fetch_public_candles(product_id, granularity, w_start, w_end)

        return public_fetch

    key_name = state.key_reference
    private_key = secrets.get_secret(SECRET_KEY)
    if key_name is None or private_key is None:
        _fail(
            "A credential appears connected but its secret is unavailable. "
            "Reconnect from the app."
        )
    client = CoinbaseRestClient(key_name=key_name, private_key_pem=private_key)

    def authenticated_fetch(w_start: datetime, w_end: datetime) -> CandlePageLike:
        return client.get_candles(product_id, granularity, w_start, w_end)

    return authenticated_fetch


def _print_summary(summary: ImportSummary) -> None:
    print(
        f"Imported {summary.imported} new candles for {summary.product_id} @ "
        f"{summary.timeframe} ({summary.granularity}); duplicates skipped: "
        f"{summary.duplicates}; rejected: {summary.rejected}."
    )
    if not summary.missing_ranges:
        print("No missing intervals in the requested range.")
        return
    print(f"Missing intervals after import: {len(summary.missing_ranges)}")
    for m_start, m_end in summary.missing_ranges[:10]:
        print(f"  {m_start:%Y-%m-%d %H:%M} → {m_end:%Y-%m-%d %H:%M} UTC")
    if len(summary.missing_ranges) > 10:
        print(f"  … and {len(summary.missing_ranges) - 10} more")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import historical candles into the local database."
    )
    parser.add_argument("--product", choices=PRODUCTS, default="BTC-USD")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, default="1h")
    parser.add_argument("--days", type=int, default=30, help="Import the last N days (default 30).")
    parser.add_argument("--start", help="ISO start date (UTC), e.g. 2026-01-01")
    parser.add_argument("--end", help="ISO end date (UTC), e.g. 2026-02-01")
    parser.add_argument(
        "--data-dir",
        help="Override the application data directory (default: the per-user app data dir).",
    )
    args = parser.parse_args()

    start, end = resolve_range(args)
    data_dir = ensure_data_dir(Path(args.data_dir) if args.data_dir else default_data_dir())
    database = Database(data_dir / "engine.db")
    upgrade_to_head(database, backup_dir=data_dir / "backups")

    fetch_page = _build_fetch(database, args.product, args.timeframe)
    importer = CandleImporter(database)
    try:
        summary = importer.import_history(
            fetch_page=fetch_page,
            product_id=args.product,
            timeframe=args.timeframe,
            start=start,
            end=end,
            progress=lambda p: print(
                f"window {p.windows_done}/{p.windows_total} — new {p.candles_new}, "
                f"rejected {p.candles_rejected}"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - operator-facing CLI prints a plain message
        _fail(f"Import stopped: {exc}")
    else:
        _print_summary(summary)


if __name__ == "__main__":
    main()
