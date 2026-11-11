"""Relative Strength Index using Wilder's smoothing (implementation.md §8).

Warm-up: the first ``period`` outputs are ``None``; the first numeric
value (index ``period``) is the simple mean of the first ``period``
price changes; from there Wilder smoothing applies
(``avg = (prev_avg * (period - 1) + change) / period``).

Documented edge conventions:
- all losses in the window → RSI 0;
- all gains in the window → RSI 100;
- a perfectly flat series (no gains, no losses) → RSI 50 (neutral, since
  RS is 0/0 and no direction is known).
"""

from __future__ import annotations

from decimal import Decimal

FLAT_RSI = 50.0


def rsi(values: list[Decimal], period: int) -> list[float | None]:
    """Return one RSI output per input value (``None`` during warm-up)."""
    if period < 1:
        raise ValueError("RSI period must be at least 1.")
    if len(values) < period + 1:
        return [None] * len(values)

    changes = [float(values[i] - values[i - 1]) for i in range(1, len(values))]
    output: list[float | None] = [None] * len(values)

    first_gains = sum(change for change in changes[:period] if change > 0) / period
    first_losses = sum(-change for change in changes[:period] if change < 0) / period
    output[period] = _rsi_value(first_gains, first_losses)
    avg_gain, avg_loss = first_gains, first_losses

    for index in range(period + 1, len(values)):
        change = changes[index - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        output[index] = _rsi_value(avg_gain, avg_loss)
    return output


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0 and avg_loss == 0:
        return FLAT_RSI
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
