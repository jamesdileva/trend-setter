"""WebSocket wire-message normalization into internal events (Sprint 5 task 2).

Envelope shape per the verified WebSocket docs (Sprint 0, checklist item 3):

    {"channel": "candles", "sequence_num": N, "timestamp": "...",
     "events": [{"type": "snapshot"|"update", "candles": [...]}]}

WS candle objects carry ``product_id`` (unlike the REST payload) but no
granularity — the configured granularity is stamped here. Unparseable or
unknown frames become :class:`IgnoredMessage` entries, never exceptions:
a malformed frame must not take down the feed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from trendbot.market_data.candles import Candle


@dataclass(frozen=True)
class CandleEvent:
    """One candle from the live feed (in-progress until rollover is observed)."""

    candle: Candle
    event_type: str  # "snapshot" | "update"
    sequence_num: int | None
    received_at: datetime


@dataclass(frozen=True)
class HeartbeatEvent:
    """Channel liveness signal (~1/second on the heartbeats channel)."""

    counter: int | None
    sequence_num: int | None
    received_at: datetime


@dataclass(frozen=True)
class SubscriptionAck:
    channel: str
    received_at: datetime


@dataclass(frozen=True)
class IgnoredMessage:
    reason: str


NormalizedEvent = CandleEvent | HeartbeatEvent | SubscriptionAck | IgnoredMessage


def normalize_message(
    raw: str | bytes,
    *,
    default_granularity: str,
    received_at: datetime | None = None,
) -> list[NormalizedEvent]:
    """Parse one wire frame into zero or more internal events."""
    arrival = received_at or datetime.now(UTC)
    try:
        payload = json.loads(raw)
    except ValueError:
        return [IgnoredMessage(reason="unparseable frame")]
    if not isinstance(payload, dict):
        return [IgnoredMessage(reason="frame is not an object")]

    channel = payload.get("channel")
    sequence_num = payload.get("sequence_num")
    sequence = int(sequence_num) if isinstance(sequence_num, (int, str)) else None

    if channel == "heartbeats":
        counter = None
        events = payload.get("events")
        if isinstance(events, list) and events and isinstance(events[0], dict):
            raw_counter = events[0].get("heartbeat_counter")
            if isinstance(raw_counter, (int, str)):
                counter = int(raw_counter)
        return [HeartbeatEvent(counter=counter, sequence_num=sequence, received_at=arrival)]

    if channel == "subscriptions":
        return [SubscriptionAck(channel="subscriptions", received_at=arrival)]

    if channel == "candles":
        events = payload.get("events")
        if not isinstance(events, list):
            return [IgnoredMessage(reason="candles frame without events")]
        results: list[NormalizedEvent] = []
        for entry in events:
            if not isinstance(entry, dict):
                continue
            event_type = str(entry.get("type", "unknown"))
            candles = entry.get("candles")
            if not isinstance(candles, list):
                continue
            for item in candles:
                if not isinstance(item, dict):
                    continue
                candle = _parse_ws_candle(item, default_granularity)
                if candle is None:
                    continue
                results.append(
                    CandleEvent(
                        candle=candle,
                        event_type=event_type,
                        sequence_num=sequence,
                        received_at=arrival,
                    )
                )
        return results

    return [IgnoredMessage(reason=f"unhandled channel {channel!r}")]


def _parse_ws_candle(item: dict[str, object], default_granularity: str) -> Candle | None:
    """Parse one WS candle object; return None (skip) on unusable entries."""
    from decimal import Decimal, InvalidOperation

    try:
        start_unix = int(str(item["start"]))
        product_id = str(item["product_id"])
        values = {
            name: Decimal(str(item[name]))
            for name in ("open", "high", "low", "close", "volume")
        }
    except (KeyError, ValueError, InvalidOperation):
        return None
    candle = Candle(
        product_id=product_id,
        granularity=default_granularity,
        start_time=datetime.fromtimestamp(start_unix, tz=UTC),
        open=values["open"],
        high=values["high"],
        low=values["low"],
        close=values["close"],
        volume=values["volume"],
        is_complete=False,
    )
    if candle.validate():
        return None
    return candle
