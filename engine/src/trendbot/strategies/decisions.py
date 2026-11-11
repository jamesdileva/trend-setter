"""Typed strategy decision model (architecture.md §8).

A decision is evidence, not an order: it carries the signal, the candle it
was made on, the indicator values used, and plain-language reasoning.
Strategies produce these; only the execution layer (later sprint) turns
risk-approved intents into exchange calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class SignalType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class StrategyPosition:
    """The current position as known to the strategy (exchange truth wins)."""

    side: str  # "long" | "flat"
    size: Decimal


FLAT_POSITION = StrategyPosition(side="flat", size=Decimal("0"))


@dataclass(frozen=True)
class StrategyDecision:
    product_id: str
    timeframe: str
    candle_time: datetime
    signal: SignalType
    reason_code: str
    explanation: str
    indicator_values: dict[str, str]
    strategy_name: str
    strategy_version: str
    config_hash: str

    def indicator_evidence_text(self) -> str:
        """Human-readable one-line evidence (UI and logs)."""
        parts = [f"{name}={value}" for name, value in sorted(self.indicator_values.items())]
        return ", ".join(parts)
