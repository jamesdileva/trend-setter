"""Offline tests for WebSocket wire-message normalization (Sprint 5 task 2)."""

import json
from datetime import UTC, datetime

from trendbot.market_data.ws_events import (
    CandleEvent,
    HeartbeatEvent,
    IgnoredMessage,
    SubscriptionAck,
    normalize_message,
)

RECEIVED = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def candles_frame(entries: list[object], seq: int | None = 7) -> str:
    frame: dict[str, object] = {"channel": "candles", "events": entries}
    if seq is not None:
        frame["sequence_num"] = seq
    return json.dumps(frame)


def wire_candle(start_unix: int = 1767259200, product: str = "BTC-USD") -> dict[str, str]:
    return {
        "start": str(start_unix),
        "product_id": product,
        "open": "100",
        "high": "102",
        "low": "98",
        "close": "101",
        "volume": "1.5",
    }


class TestNormalization:
    def test_candle_events_carry_the_stamped_granularity_and_product(self):
        events = normalize_message(
            candles_frame([{"type": "update", "candles": [wire_candle()]}]),
            default_granularity="FIVE_MINUTE",
            received_at=RECEIVED,
        )
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, CandleEvent)
        assert event.candle.granularity == "FIVE_MINUTE"
        assert event.candle.product_id == "BTC-USD"
        assert event.event_type == "update"
        assert event.sequence_num == 7
        assert event.received_at == RECEIVED
        assert event.candle.is_complete is False

    def test_snapshot_with_multiple_candles_yields_multiple_events(self):
        frame = candles_frame(
            [{"type": "snapshot", "candles": [wire_candle(), wire_candle(start_unix=1767259500)]}],
            seq=3,
        )
        events = normalize_message(frame, default_granularity="FIVE_MINUTE", received_at=RECEIVED)
        assert len(events) == 2
        assert all(isinstance(event, CandleEvent) for event in events)

    def test_heartbeat_event_extracts_the_counter(self):
        frame = json.dumps(
            {
                "channel": "heartbeats",
                "sequence_num": 42,
                "events": [{"heartbeat_counter": "17", "current_time": "2026-01-01T12:00:00Z"}],
            }
        )
        events = normalize_message(frame, default_granularity="FIVE_MINUTE", received_at=RECEIVED)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, HeartbeatEvent)
        assert event.counter == 17
        assert event.sequence_num == 42

    def test_subscription_acks_are_recognized(self):
        frame = json.dumps(
            {
                "channel": "subscriptions",
                "events": [{"channel": "candles", "products": ["BTC-USD"]}],
            }
        )
        events = normalize_message(frame, default_granularity="FIVE_MINUTE", received_at=RECEIVED)
        assert len(events) == 1
        assert isinstance(events[0], SubscriptionAck)

    def test_unparseable_frames_are_ignored_safely(self):
        events = normalize_message("<not json>", default_granularity="FIVE_MINUTE")
        assert events == [IgnoredMessage(reason="unparseable frame")]

    def test_unknown_channels_are_ignored_safely(self):
        frame = json.dumps({"channel": "level2", "events": []})
        events = normalize_message(frame, default_granularity="FIVE_MINUTE")
        assert events and isinstance(events[0], IgnoredMessage)

    def test_unusable_candle_entries_are_skipped_not_fatal(self):
        broken = {"start": "nope", "product_id": "BTC-USD"}
        frame = candles_frame([{"type": "update", "candles": [broken, wire_candle()]}])
        events = normalize_message(frame, default_granularity="FIVE_MINUTE")
        candle_events = [event for event in events if isinstance(event, CandleEvent)]
        assert len(candle_events) == 1
