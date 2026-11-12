"""Idempotent fill application (roadmap Sprint 8 task 9).

A fill is stored once (unique entry identity) and applied to the position
snapshot exactly once — replayed fill events never double-count. BUY
fills accumulate the position; SELL fills reduce it, never below zero.
"""

from __future__ import annotations

from trendbot.database.repositories import FillRepository, PositionRepository
from trendbot.database.session import Database
from trendbot.exchange.types import Fill


def apply_fill_idempotent(database: Database, fill: Fill) -> bool:
    """Store and apply one fill. Returns False for replayed events."""
    recorded = FillRepository(database).record_fill(fill)
    if not recorded:
        return False
    PositionRepository(database).apply_fill(fill)
    return True
