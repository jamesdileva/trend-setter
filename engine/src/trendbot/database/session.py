"""Database handle: connections, PRAGMAs, transactions, and health signals.

SQLite configuration follows architecture.md §14: foreign keys enabled,
WAL journal mode, busy timeout, transactional writes, and centralized
write ownership through this object's sessions.

The database is always a file on persistent storage — never an ephemeral
in-memory store — so state survives restarts (vps-deployment.md §9).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from trendbot.database.models import EngineEvent

BUSY_TIMEOUT_MS = 5000


class DatabaseWriteError(RuntimeError):
    """A durable write failed and was rolled back; no partial changes were kept."""


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    """Apply the required SQLite PRAGMAs to every new connection."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    cursor.close()


class Database:
    """Owns the SQLAlchemy engine and all durable writes for the app."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.url = f"sqlite:///{self.path.resolve().as_posix()}"
        self._engine: Engine = create_engine(self.url, future=True)
        event.listen(self._engine, "connect", _configure_connection)

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional session: commits on success, rolls back on any error.

        All durable writes must go through this context (architecture.md
        §14: "Use transactions for state transitions"). Failures are
        re-raised as :class:`DatabaseWriteError` with the original cause
        chained, so callers can record a health event and keep running.
        """
        session = Session(self._engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except Exception as exc:
            session.rollback()
            raise DatabaseWriteError(
                "The database write failed and was rolled back; no partial changes were kept."
            ) from exc
        finally:
            session.close()

    def write_failure(self, component: str, detail: str) -> bool:
        """Record a write failure for the health view (best effort).

        ``detail`` must already be redacted — this layer does not filter
        secrets. Returns False when even the failure record cannot be
        written (e.g. disk full), which the caller must treat as critical.
        """
        try:
            with self.session() as session:
                session.add(
                    EngineEvent(
                        event_type="database_write_failed",
                        component=component,
                        message=(
                            "A database write failed; the engine recorded this "
                            "for the health view."
                        ),
                        detail={"detail": detail},
                    )
                )
            return True
        except Exception:
            return False

    def execute_scalar(self, statement: str) -> object:
        """Run a read-only statement and return the first value, if any."""
        with self._engine.connect() as connection:
            return connection.execute(text(statement)).scalar()
