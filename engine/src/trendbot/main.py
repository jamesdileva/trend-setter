"""Engine entrypoint (architecture.md §5).

The engine binds to ``127.0.0.1`` only and accepts no host override — a
public bind would violate the local-first boundary. The local session
token arrives via the environment (set by the supervisor), never on the
command line (implementation.md §12).
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from trendbot.api.app import create_app

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
    app = create_app(local_token=os.environ.get("TRENDBOT_LOCAL_TOKEN"))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
