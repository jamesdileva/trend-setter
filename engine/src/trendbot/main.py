"""Engine entrypoint (architecture.md §5).

The engine binds to ``127.0.0.1`` only and accepts no host override — a
public bind would violate the local-first boundary. The local session
token arrives via the environment (set by the supervisor), never on the
command line (implementation.md §12).

Startup verifies the database schema first (Sprint 2 migrations, with a
pre-migration backup of existing data); trading behavior must never start
on an unverified schema.
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from trendbot.api.app import create_app
from trendbot.config.paths import default_data_dir, ensure_data_dir
from trendbot.database import Database, MigrationError, upgrade_to_head
from trendbot.security.secret_store import default_secret_store

DEFAULT_PORT = 8788


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
    database = Database(data_dir / "engine.db")
    try:
        upgrade_to_head(database, backup_dir=data_dir / "backups")
    except MigrationError as exc:
        raise SystemExit(f"Engine startup failed during a database upgrade: {exc}") from exc

    app = create_app(
        os.environ.get("TRENDBOT_LOCAL_TOKEN"),
        database=database,
        secret_store=default_secret_store(),
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
