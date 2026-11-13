"""Migration execution with pre-upgrade backup and failure handling.

Roadmap Sprint 2 tasks 3 and 8: Alembic migrations, and "migration backup
and failure handling". ``upgrade_to_head`` snapshots an existing database
before migrating, and wraps failures in a plain-language error that names
the backup location. SQLite DDL is transactional and Alembic runs each
revision in a transaction, so a failed upgrade leaves the version
unchanged.
"""

from __future__ import annotations

import sys

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

from trendbot.database.backup import backup_database
from trendbot.database.session import Database

def _find_engine_root() -> Path:
    """Find the engine root for Alembic config, handling both source tree
    and PyInstaller bundle layouts."""
    # Source tree: migrations.py is at src/trendbot/database/migrations.py
    # → parents[3] = engine/
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "alembic.ini").exists():
        return source_root
    # PyInstaller bundle: data files are placed in _MEIPASS (onedir: _internal/)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass)
        if (bundled / "migrations").exists():
            return bundled
    # Fallback: the exe's own directory (onedir layout)
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "migrations").exists():
        return exe_dir
    return source_root


_ENGINE_ROOT = _find_engine_root()


class MigrationError(RuntimeError):
    """A database upgrade failed; the previous state is preserved."""


def _alembic_config(url: str) -> Config:
    script_location = _ENGINE_ROOT / "migrations"
    ini_path = _ENGINE_ROOT / "alembic.ini"
    if ini_path.exists():
        config = Config(str(ini_path))
    else:
        config = Config()
        config.set_main_option("script_location", str(script_location))
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade_to_head(database: Database, *, backup_dir: Path | None = None) -> Path | None:
    """Bring the database schema to the latest migration.

    When the database already holds data and ``backup_dir`` is provided,
    a timestamped pre-migration backup is written first (architecture.md
    §14: "Back up database before migrations"). Returns the backup path,
    or None when no backup was taken (fresh/empty database or no dir).
    """
    backup_path: Path | None = None
    if (
        backup_dir is not None
        and database.path is not None
        and database.path.exists()
        and database.path.stat().st_size > 0
    ):
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup_path = backup_database(
            database, backup_dir / f"pre-migration-{stamp}{database.path.suffix or '.db'}"
        )
    try:
        command.upgrade(_alembic_config(database.url), "head")
    except Exception as exc:
        detail = f": {backup_path}" if backup_path is not None else ""
        raise MigrationError(
            "The database upgrade failed and the schema version is unchanged. "
            f"No known-good backup was needed for a fresh database.{detail} "
            "If a backup was taken, it is listed in the message above."
        ) from exc
    return backup_path
