"""Column types encoding the persistence conventions (architecture.md §14).

- ``DecimalString``: money and quantities are stored as exact decimal
  strings — binary floats are rejected at the boundary, so no
  float-corruption can enter financial values.
- ``UtcDateTime``: timestamps are UTC. Timezone-aware datetimes are
  required on write and normalized to UTC; stored without offset and
  returned tagged with UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import DateTime, String, TypeDecorator


class DecimalString(TypeDecorator[Decimal]):
    """Store :class:`~decimal.Decimal` values as exact decimal strings."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(
                "Decimal columns require Decimal values; binary floats are not allowed."
            )
        return str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - corrupted row guard
            raise ValueError(f"Stored value {value!r} is not a valid decimal string.") from exc


class UtcDateTime(TypeDecorator[datetime]):
    """Store timezone-aware UTC datetimes; always return them tagged UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware; store UTC datetimes.")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)
