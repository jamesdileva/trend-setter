"""Bounded exponential backoff with jitter (architecture.md §18).

Retry guidance verified in Sprint 0 (checklist item 7): honor
``Retry-After`` when present; otherwise bounded exponential backoff with
jitter; reduce concurrency instead of retrying continuously. Never used
for ambiguous order creation (architecture.md §10) — only for retryable
reads such as market data.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 8.0
JITTER_FRACTION = 0.25


def with_backoff(
    attempt: Callable[[], T],
    *,
    is_retryable: Callable[[BaseException], bool],
    retry_after: Callable[[BaseException], float | None] | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    base_delay: float = BASE_DELAY_SECONDS,
    max_delay: float = MAX_DELAY_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Run ``attempt``, retrying retryable failures with backoff.

    Non-retryable failures and exhausted attempts re-raise immediately.
    ``retry_after`` (when provided) overrides the computed delay, honoring
    the server's instruction, still capped at ``max_delay``. ``sleep``
    defaults to ``time.sleep`` resolved at call time (testable).
    """
    sleeper = sleep if sleep is not None else time.sleep
    for attempt_number in range(1, max_attempts + 1):
        try:
            return attempt()
        except BaseException as exc:
            if not is_retryable(exc) or attempt_number == max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt_number - 1)), max_delay)
            if retry_after is not None:
                hint = retry_after(exc)
                if hint is not None:
                    delay = min(hint, max_delay)
            sleeper(delay + random.uniform(0, JITTER_FRACTION * delay))
    raise AssertionError("unreachable: retry loop always returns or raises")  # pragma: no cover
