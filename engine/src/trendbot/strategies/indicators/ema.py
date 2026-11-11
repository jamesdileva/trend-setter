"""Exponential moving average with a documented SMA seed (implementation.md §8).

Warm-up: the first ``period - 1`` outputs are ``None``; output at index
``period - 1`` is the simple moving average seed; from there the standard
recursive EMA applies with smoothing factor ``k = 2 / (period + 1)``. For a
constant input series the EMA equals that constant exactly.
"""

from __future__ import annotations

from decimal import Decimal


def ema(values: list[Decimal], period: int) -> list[float | None]:
    """Return one EMA output per input value (``None`` during warm-up)."""
    if period < 1:
        raise ValueError("EMA period must be at least 1.")
    if len(values) < period:
        return [None] * len(values)

    k = 2.0 / (period + 1)
    output: list[float | None] = [None] * len(values)
    seed = sum(float(value) for value in values[:period]) / period
    output[period - 1] = seed
    previous = seed
    for index in range(period, len(values)):
        current = float(values[index])
        previous = (current - previous) * k + previous
        output[index] = previous
    return output
