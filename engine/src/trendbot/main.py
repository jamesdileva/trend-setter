"""Engine entrypoint (architecture.md §5).

The engine binds to ``127.0.0.1`` only and accepts no host override — a
public bind would violate the local-first boundary. The local session
token arrives via the environment (set by the supervisor), never on the
command line (implementation.md §12).

Startup verifies the database schema first (Sprint 2 migrations, with a
pre-migration backup of existing data); trading behavior must never start
on an unverified schema. The live market-data feed (Sprint 5) runs on the
public channels — no credentials needed for market data.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
from datetime import UTC, datetime

import uvicorn

from trendbot.api.app import create_app
from trendbot.application.live_trading import LiveArmingController
from trendbot.config.paths import default_data_dir, ensure_data_dir
from trendbot.database import Database, MigrationError, backup_database, upgrade_to_head
from trendbot.database.repositories import CandleRepository, EngineEventRepository
from trendbot.market_data.backfill import GapBackfiller
from trendbot.market_data.live_feed import PUBLIC_WS_URL, CandleFeed, FeedStatus
from trendbot.market_data.source import build_fetch_page
from trendbot.market_data.ws_transport import websockets_transport_factory
from trendbot.security.secret_store import default_secret_store

DEFAULT_PORT = 8788
DEFAULT_PRODUCTS = ("BTC-USD", "ETH-USD")
FEED_TIMEFRAME = "5m"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the trendbot engine local API (loopback only)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Loopback port for the local API (default: %(default)s).",
    )
    args = parser.parse_args()

    data_dir = ensure_data_dir(default_data_dir())
    log_dir = ensure_data_dir(data_dir / "logs")

    # Rotating file handler: daily rotation, 7-day retention
    handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "engine.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s"))
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)

    database = Database(data_dir / "engine.db")
    try:
        upgrade_to_head(database, backup_dir=data_dir / "backups")
    except MigrationError as exc:
        raise SystemExit(f"Engine startup failed during a database upgrade: {exc}") from exc

    feed_status = FeedStatus()
    backfiller = GapBackfiller(
        database,
        fetch_builder=lambda product_id, timeframe: build_fetch_page(
            database, product_id, timeframe
        ),
    )

    async def on_gap(
        product_id: str, timeframe: str, gap_start: datetime, gap_end: datetime
    ) -> None:
        await backfiller.backfill(product_id, timeframe, gap_start, gap_end)

    def feed_factory() -> CandleFeed:
        return CandleFeed(
            url=PUBLIC_WS_URL,
            product_ids=list(DEFAULT_PRODUCTS),
            timeframe=FEED_TIMEFRAME,
            transport_factory=websockets_transport_factory(PUBLIC_WS_URL),
            repository=CandleRepository(database),
            events=EngineEventRepository(database),
            status=feed_status,
            on_gap=on_gap,
        )

    # Restart never silently resumes live trading (R-06): force-disarm.
    LiveArmingController(database).force_disarm()

    app = create_app(
        os.environ.get("TRENDBOT_LOCAL_TOKEN"),
        database=database,
        secret_store=default_secret_store(),
        feed_factory=feed_factory,
        market_status_provider=feed_status.snapshot,
        on_shutdown=lambda: backup_database(
            database,
            data_dir / "backups"
            / f"shutdown-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db",
        ),
    )
    # access_log=False: per-request lines went to stderr, which the desktop
    # supervisor pipes but cannot drain fast enough — the pipe buffer filled
    # after ~20 minutes and blocked the engine's event loop (frozen API).
    # Request activity is visible via the DB events and the file log instead.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
