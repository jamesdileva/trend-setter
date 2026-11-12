"""Table-driven state machine tests: every legal transition accepted,
illegal ones rejected with plain-language errors (Sprint 8 task 6)."""

import pytest

from trendbot.execution.state_machine import (
    ACKNOWLEDGED,
    CANCELED,
    CREATED,
    EXPIRED,
    FILLED,
    LEGAL_TRANSITIONS,
    OPEN,
    PARTIALLY_FILLED,
    RECONCILIATION_REQUIRED,
    REJECTED,
    RISK_APPROVED,
    SUBMITTING,
    UNKNOWN_SUBMISSION,
    is_terminal,
    is_unresolved,
    validate_transition,
)


def all_legal_pairs() -> list[tuple[str, str]]:
    return [
        (current, new)
        for current, news in LEGAL_TRANSITIONS.items()
        for new in news
    ]


class TestLegalTransitions:
    def test_the_happy_path_walks_end_to_end(self):
        states = [
            CREATED,
            RISK_APPROVED,
            SUBMITTING,
            ACKNOWLEDGED,
            OPEN,
            PARTIALLY_FILLED,
            FILLED,
        ]
        # Intentional off-by-one pairing: each state with its successor.
        for current, new in zip(states, states[1:], strict=False):
            assert validate_transition(current, new) == new

    @pytest.mark.parametrize(("current", "new"), all_legal_pairs())
    def test_every_legal_transition_in_the_table_is_accepted(self, current, new):
        assert validate_transition(current, new) == new


class TestIllegalTransitions:
    @pytest.mark.parametrize(
        ("current", "new"),
        [
            (CREATED, OPEN),  # cannot skip the risk gate
            (CREATED, SUBMITTING),
            (RISK_APPROVED, OPEN),
            (SUBMITTING, OPEN),  # must be acknowledged first
            (OPEN, CREATED),
            (FILLED, OPEN),  # terminal
            (CANCELED, OPEN),
            (REJECTED, SUBMITTING),
            (UNKNOWN_SUBMISSION, OPEN),  # must reconcile first
            (PARTIALLY_FILLED, CREATED),
        ],
    )
    def test_illegal_transitions_are_rejected_plain_language(self, current, new):
        with pytest.raises(Exception) as excinfo:
            validate_transition(current, new)
        message = str(excinfo.value)
        assert "Illegal order transition" in message or "final state" in message

    def test_terminal_states_accept_nothing(self):
        for terminal in (FILLED, CANCELED, REJECTED, EXPIRED):
            with pytest.raises(Exception) as excinfo:
                validate_transition(terminal, OPEN)
            assert "final state" in str(excinfo.value)


class TestHelpers:
    def test_terminal_detection(self):
        assert is_terminal(FILLED) and is_terminal(REJECTED)
        assert not is_terminal(OPEN) and not is_terminal(SUBMITTING)

    def test_unresolved_detection(self):
        assert is_unresolved(UNKNOWN_SUBMISSION)
        assert is_unresolved(RECONCILIATION_REQUIRED)
        assert is_unresolved(OPEN)
        assert not is_unresolved(FILLED)
        assert not is_unresolved(CANCELED)
