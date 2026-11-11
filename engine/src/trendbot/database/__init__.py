"""Database layer: models, migrations, repositories, and transaction helpers.

Write ownership is centralized here (architecture.md §14): other layers
persist and read through this package's repositories, never through
ad-hoc SQL or raw connections.
"""

from trendbot.database.backup import backup_database, integrity_check, restore_database
from trendbot.database.migrations import MigrationError, upgrade_to_head
from trendbot.database.repositories import (
    CandleRepository,
    EngineEventRepository,
    FillRepository,
    SettingsRepository,
)
from trendbot.database.session import Database, DatabaseWriteError

__all__ = [
    "CandleRepository",
    "Database",
    "DatabaseWriteError",
    "EngineEventRepository",
    "FillRepository",
    "MigrationError",
    "SettingsRepository",
    "backup_database",
    "integrity_check",
    "restore_database",
    "upgrade_to_head",
]
