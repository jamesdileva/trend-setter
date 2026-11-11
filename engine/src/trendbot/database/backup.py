"""Backup, integrity-check, and restore utilities (architecture.md §14).

- Backups use the SQLite backup API, which produces a consistent snapshot
  even while the database is in WAL mode and being written.
- Restore deliberately refuses to overwrite an existing database file:
  replacing a live database is a separate, explicit operator action.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import cast

from trendbot.database.session import Database


def backup_database(database: Database, destination: Path) -> Path:
    """Write a consistent snapshot of ``database`` to ``destination``.

    Creates parent directories as needed. Returns the destination path.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = destination.with_suffix(".db") if destination.suffix == "" else destination
    with database.engine.connect() as connection:
        source_conn = cast("sqlite3.Connection", connection.connection.driver_connection)
        target_conn = sqlite3.connect(destination)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
    return destination


def integrity_check(database: Database) -> list[str]:
    """Run ``PRAGMA integrity_check``; return problems (empty list = healthy)."""
    result = database.execute_scalar("PRAGMA integrity_check")
    if result is None or result == "ok":
        return []
    return [str(result)]


def restore_database(backup_path: Path, target_path: Path) -> Path:
    """Restore a backup into a clean database file and verify it.

    Refuses to overwrite an existing file — call an explicit delete first
    if a replacement is truly intended (never silently).
    """
    if target_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing database at {target_path}. "
            "Move or delete it first; restoring is a deliberate operator action."
        )
    if backup_path.resolve() == target_path.resolve():
        raise ValueError("The backup path and the restore target are the same file.")
    probe = sqlite3.connect(backup_path)
    try:
        check = probe.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(
            f"The file at {backup_path} is not a readable SQLite database and was not restored."
        ) from exc
    finally:
        probe.close()
    if check is None or check[0] != "ok":
        raise ValueError(
            f"The backup at {backup_path} failed its integrity check and was not restored."
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup_path, target_path)
    verify = sqlite3.connect(target_path)
    try:
        check = verify.execute("PRAGMA integrity_check").fetchone()
    finally:
        verify.close()
    if check is None or check[0] != "ok":
        raise ValueError(f"The restored database at {target_path} failed its integrity check.")
    return target_path
