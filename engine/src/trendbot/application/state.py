"""Engine lifecycle state (architecture.md §5).

The skeleton starts in ``READY_PAPER``: paper-first, live trading is a
separate, deliberately-armed workflow added in later sprints. Live states
(``LIVE_NOT_ARMED`` and beyond) are placeholders until the live-readiness
gate exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EngineState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    READY_PAPER = "ready_paper"
    RUNNING_PAPER = "running_paper"
    STOPPING = "stopping"
    LIVE_NOT_ARMED = "live_not_armed"
    DEGRADED = "degraded"
    SAFE_HALT = "safe_halt"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass
class EngineRuntime:
    """Current lifecycle snapshot exposed through the local API.

    The engine is a single-instance process, so one mutable snapshot is
    sufficient until concurrent state transitions arrive with the
    execution sprints.
    """

    state: EngineState = EngineState.READY_PAPER
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def uptime_seconds(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()
