"""Application data locations (architecture.md §17).

Mutable data (database, logs, backups) lives under the user's application
data directory — never inside an installation directory, never in the repo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "trend-setter"


def default_data_dir() -> Path:
    """Return the per-user application data directory for this app."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def ensure_data_dir(path: Path) -> Path:
    """Create the data directory (and parents) if missing; return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
