"""Order intent state machine (architecture.md §10).

Durable state transitions are table-driven: every legal transition is
explicit, everything else is illegal and raises a plain-language error.
States match the persisted ``order_intents.state`` values.
"""

from __future__ import annotations

from trendbot.strategies.config import StrategyConfigError

CREATED = "created"
RISK_APPROVED = "risk_approved"
SUBMITTING = "submitting"
ACKNOWLEDGED = "acknowledged"
OPEN = "open"
PARTIALLY_FILLED = "partially_filled"
FILLED = "filled"
REJECTED = "rejected"
CANCEL_PENDING = "cancel_pending"
CANCELED = "canceled"
EXPIRED = "expired"
UNKNOWN_SUBMISSION = "unknown_submission"
RECONCILIATION_REQUIRED = "reconciliation_required"

TERMINAL_STATES = frozenset({FILLED, CANCELED, REJECTED, EXPIRED})

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({RISK_APPROVED, REJECTED}),
    RISK_APPROVED: frozenset({SUBMITTING, REJECTED}),
    SUBMITTING: frozenset({ACKNOWLEDGED, UNKNOWN_SUBMISSION, REJECTED}),
    ACKNOWLEDGED: frozenset({OPEN, REJECTED}),
    OPEN: frozenset({PARTIALLY_FILLED, FILLED, CANCEL_PENDING}),
    PARTIALLY_FILLED: frozenset({PARTIALLY_FILLED, FILLED, CANCEL_PENDING}),
    CANCEL_PENDING: frozenset({CANCELED, FILLED}),
    UNKNOWN_SUBMISSION: frozenset({RECONCILIATION_REQUIRED}),
    RECONCILIATION_REQUIRED: frozenset({OPEN, FILLED, CANCELED, ACKNOWLEDGED}),
    FILLED: frozenset(),
    CANCELED: frozenset(),
    REJECTED: frozenset(),
    EXPIRED: frozenset(),
}


def validate_transition(current: str, new: str) -> str:
    """Return ``new`` when the transition is legal; raise otherwise."""
    legal = LEGAL_TRANSITIONS.get(current)
    if legal is None:
        raise StrategyConfigError(
            f"Unknown order state {current!r}; the intent ledger may be corrupted."
        )
    if current in TERMINAL_STATES:
        raise StrategyConfigError(
            f"Order is already in a final state ({current}); no further transitions are allowed."
        )
    if new not in legal:
        raise StrategyConfigError(
            f"Illegal order transition {current!r} → {new!r}. "
            f"Allowed next states: {', '.join(sorted(legal)) or 'none'}."
        )
    return new


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_unresolved(state: str) -> bool:
    """States that need attention after a restart or reconnect."""
    return state in {
        CREATED,
        RISK_APPROVED,
        SUBMITTING,
        UNKNOWN_SUBMISSION,
        ACKNOWLEDGED,
        OPEN,
        PARTIALLY_FILLED,
        CANCEL_PENDING,
        RECONCILIATION_REQUIRED,
    }
