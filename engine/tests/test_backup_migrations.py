"""Tests for migrations, pre-migration backups, and restore (Sprint 2 verification).

Covers: fresh-database upgrades, the schema_migrations history table,
pre-upgrade backup creation, wrapped migration failures, backup/restore
round-trips into a clean database, and restore refusing to overwrite.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect as sa_inspect

import trendbot.database.migrations as migrations_module
from trendbot.database import (
    CandleRepository,
    Database,
    MigrationError,
    SettingsRepository,
    backup_database,
    integrity_check,
    restore_database,
    upgrade_to_head,
)
from trendbot.database.models import CORE_TABLES
from trendbot.market_data.candles import Candle


@pytest.fixture()
def upgraded_db(tmp_path):
    database = Database(tmp_path / "appdata.db")
    upgrade_to_head(database)
    return database


def sample_candle() -> Candle:
    return Candle(
        product_id="BTC-USD",
        granularity="ONE_HOUR",
        start_time=datetime(2026, 1, 1, 13, tzinfo=UTC),
        open=Decimal("65000.13"),
        high=Decimal("65001.99"),
        low=Decimal("64998.01"),
        close=Decimal("65000.50"),
        volume=Decimal("12.3456789"),
    )


class TestMigrations:
    def test_migrations_upgrade_a_fresh_database(self, upgraded_db):
        inspector = sa_inspect(upgraded_db.engine)
        tables = set(inspector.get_table_names())
        for table in CORE_TABLES:
            assert table in tables
        assert "schema_migrations" in tables
        assert integrity_check(upgraded_db) == []

    def test_pre_migration_backup_is_taken_for_an_existing_database(self, upgraded_db, tmp_path):
        SettingsRepository(upgraded_db).set("seed", "1")
        backup_dir = tmp_path / "backups"
        backup = upgrade_to_head(upgraded_db, backup_dir=backup_dir)
        assert backup is not None
        assert backup.exists()
        assert backup.is_file()

        # The backup is a usable database: restore it into a clean file
        # and confirm the seeded row is there.
        restored_path = restore_database(backup, tmp_path / "check" / "restored.db")
        restored = Database(restored_path)
        assert SettingsRepository(restored).get("seed") == "1"

    def test_migration_failure_is_wrapped_with_a_plain_message(
        self, upgraded_db, tmp_path, monkeypatch
    ):
        SettingsRepository(upgraded_db).set("seed", "1")
        monkeypatch.setattr(
            migrations_module.command,
            "upgrade",
            lambda config, revision: (_ for _ in ()).throw(RuntimeError("exploded")),
        )
        with pytest.raises(MigrationError) as excinfo:
            upgrade_to_head(upgraded_db, backup_dir=tmp_path / "backups")
        assert "upgrade failed" in str(excinfo.value)
        # The pre-migration backup was still taken before the failure.
        assert (tmp_path / "backups").is_dir()


class TestBackupAndRestore:
    def test_backup_restore_round_trip_into_a_clean_database(self, upgraded_db, tmp_path):
        candle_repo = CandleRepository(upgraded_db)
        candle_repo.upsert_many([sample_candle()])
        SettingsRepository(upgraded_db).set("k", "v")
        assert integrity_check(upgraded_db) == []

        backup = backup_database(upgraded_db, tmp_path / "backups" / "snapshot.db")
        restored_path = restore_database(backup, tmp_path / "restored" / "appdata.db")
        restored = Database(restored_path)

        assert integrity_check(restored) == []
        assert SettingsRepository(restored).get("k") == "v"
        stored = CandleRepository(restored).get_range(
            "BTC-USD",
            "ONE_HOUR",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert stored[0].open == Decimal("65000.13")

    def test_restore_refuses_to_overwrite_an_existing_database(self, upgraded_db, tmp_path):
        CandleRepository(upgraded_db).upsert_many([sample_candle()])
        backup = backup_database(upgraded_db, tmp_path / "backups" / "snapshot.db")
        existing_target = tmp_path / "existing.db"
        existing_target.write_bytes(b"not a database")
        with pytest.raises(FileExistsError):
            restore_database(backup, existing_target)

    def test_restore_rejects_a_corrupt_backup(self, tmp_path):
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"definitely not sqlite" * 10)
        with pytest.raises(ValueError):
            restore_database(corrupt, tmp_path / "out.db")
