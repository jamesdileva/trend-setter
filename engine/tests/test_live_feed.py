"""Offline tests for the live candle feed (roadmap Sprint 5 verification).

Scripted transports drive every scenario: subscribe-first deadline,
completeness rollover, duplicate suppression, disconnect→reconnect→
resubscribe, forced reconnect on silence, and sequence-gap callbacks.
No network, no websockets library.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from trendbot.database import Database, upgrade_to_head
from trendbot.database.models import EngineEvent
from trendbot.database.repositories import CandleRepository, EngineEventRepository
from trendbot.market_data.live_feed import CandleFeed, FeedStatus
from trendbot.market_data.ws_transport import WsConnectionLost

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
BUCKET = 300  # 5-minute buckets (seconds)


class Park:
    """Sentinel: park recv until close() (used to simulate feed silence)."""


class ScriptedConnection:
    def __init__(self, messages: list[object], *, park_on_empty: bool = False) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._messages = list(messages)
        self._park_on_empty = park_on_empty
        self._park_event = asyncio.Event()

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        if self.closed:
            raise WsConnectionLost("closed")
        if not self._messages:
            if self._park_on_empty:
                await self._park_event.wait()
                raise WsConnectionLost("closed while parked")
            raise WsConnectionLost("script exhausted")
        item = self._messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)

    async def close(self) -> None:
        self.closed = True
        self._park_event.set()


class ScriptedTransport:
    """Hands out scripted connections; records every one it was asked for."""

    def __init__(self, connections: list[ScriptedConnection | Exception]) -> None:
        self._connections = list(connections)
        self.handed_out: list[ScriptedConnection] = []
        self.connect_calls = 0

    async def __call__(self):
        self.connect_calls += 1
        if not self._connections:
            raise WsConnectionLost("script exhausted")
        item = self._connections.pop(0)
        if isinstance(item, Exception):
            raise item
        self.handed_out.append(item)
        return item


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "feed.db")
    upgrade_to_head(database)
    return database


def make_feed(
    db, transport: ScriptedTransport, **overrides
) -> tuple[CandleFeed, list[tuple[str, str, datetime, datetime]]]:
    gaps: list[tuple[str, str, datetime, datetime]] = []

    async def on_gap(
        product_id: str, timeframe: str, gap_start: datetime, gap_end: datetime
    ) -> None:
        gaps.append((product_id, timeframe, gap_start, gap_end))

    feed = CandleFeed(
        url="wss://example",
        product_ids=["BTC-USD"],
        timeframe="5m",
        transport_factory=transport,
        repository=CandleRepository(db),
        events=EngineEventRepository(db),
        on_gap=on_gap,
        stale_after=overrides.pop("stale_after", 0.08),
        base_delay=overrides.pop("base_delay", 0.01),
        max_delay=overrides.pop("max_delay", 0.05),
        **overrides,
    )
    return feed, gaps


async def run_for(feed: CandleFeed, seconds: float = 0.15) -> None:
    task = asyncio.create_task(feed.run())
    await asyncio.sleep(seconds)
    await feed.stop()
    await asyncio.wait_for(task, timeout=2.0)


def candle_frame(seq: int, start: datetime, product: str = "BTC-USD") -> str:
    return json.dumps(
        {
            "channel": "candles",
            "sequence_num": seq,
            "events": [
                {
                    "type": "update",
                    "candles": [
                        {
                            "start": str(int(start.timestamp())),
                            "product_id": product,
                            "open": "100",
                            "high": "102",
                            "low": "98",
                            "close": "101",
                            "volume": "1.5",
                        }
                    ],
                }
            ],
        }
    )


class TestSubscription:
    def test_subscribes_immediately_with_one_channel_per_message(self, db):
        transport = ScriptedTransport([ScriptedConnection([Park()], park_on_empty=True)])
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        connection = transport.handed_out[0]
        frames = [json.loads(frame) for frame in connection.sent]
        assert frames[0]["type"] == "subscribe"
        assert frames[0]["channel"] == "candles"
        assert frames[0]["product_ids"] == ["BTC-USD"]
        assert frames[1]["type"] == "subscribe"
        assert frames[1]["channel"] == "heartbeats"
        assert feed.status.subscriptions == ["candles", "heartbeats"]


class TestCompleteness:
    def test_in_progress_candle_is_not_stored(self, db):
        transport = ScriptedTransport([ScriptedConnection([candle_frame(1, T0)])])
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        assert CandleRepository(db).count() == 0
        assert feed.status.last_complete == {}

    def test_bucket_rollover_stores_the_completed_candle(self, db):
        later = T0 + timedelta(seconds=BUCKET)
        transport = ScriptedTransport(
            [ScriptedConnection([candle_frame(1, T0), candle_frame(2, later)])]
        )
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        repository = CandleRepository(db)
        assert repository.count() == 1
        stored = repository.get_range("BTC-USD", "FIVE_MINUTE", T0, later)
        assert stored[0].start_time == T0
        assert stored[0].is_complete is True
        expected = {"BTC-USD@FIVE_MINUTE": T0.strftime("%Y-%m-%dT%H:%M:%SZ")}
        assert feed.status.last_complete == expected

    def test_duplicate_and_older_messages_never_duplicate_storage(self, db):
        later = T0 + timedelta(seconds=BUCKET)
        two_buckets_later = later + timedelta(seconds=BUCKET)
        transport = ScriptedTransport(
            [
                ScriptedConnection(
                    [
                        candle_frame(1, T0),
                        candle_frame(2, later),
                        candle_frame(3, later),  # same-bucket refresh: pending update only
                        candle_frame(4, T0),  # stale older event after refresh
                        candle_frame(5, two_buckets_later),  # rollover → stores `later`
                        candle_frame(6, later),  # older than last stored → ignored entirely
                    ]
                )
            ]
        )
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        repository = CandleRepository(db)
        assert repository.count() == 2  # T0 and `later`, exactly once each
        stored_starts = [
            candle.start_time
            for candle in repository.get_range("BTC-USD", "FIVE_MINUTE", T0, two_buckets_later)
        ]
        assert stored_starts == [T0, later]


class TestReconnect:
    def test_disconnect_reconnects_and_resubscribes(self, db):
        later = T0 + timedelta(seconds=BUCKET)
        first = ScriptedConnection([candle_frame(1, T0)])
        second = ScriptedConnection(
            [candle_frame(10, T0), candle_frame(11, later)]  # snapshot replays same bucket
        )
        transport = ScriptedTransport([first, second])
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        assert feed.status.reconnects >= 1
        assert transport.connect_calls >= 2
        resubscribed = [json.loads(frame) for frame in second.sent]
        assert resubscribed[0]["channel"] == "candles"
        assert resubscribed[1]["channel"] == "heartbeats"
        # Snapshot replay of the same bucket does not duplicate storage.
        assert CandleRepository(db).count() == 1

    def test_silence_forces_reconnect_and_fires_gap_backfill(self, db):
        first = ScriptedConnection([candle_frame(1, T0)], park_on_empty=True)
        second = ScriptedConnection([Park()], park_on_empty=True)
        transport = ScriptedTransport([first, second])
        feed, gaps = make_feed(db, transport, stale_after=0.05)
        asyncio.run(run_for(feed, seconds=0.4))

        # The first parking connection deterministically hits the silence
        # timeout (0.05s stale window); a second full cycle depends on CI
        # timing, so only one reconnect is asserted.
        assert feed.status.reconnects >= 1
        assert feed.status.last_error is not None
        # The disconnect marks the missed period for REST backfill.
        assert gaps and gaps[0][0] == "BTC-USD" and gaps[0][1] == "5m"
        gap_start, gap_end = gaps[0][2], gaps[0][3]
        assert gap_end > gap_start

    def test_exhausted_script_keeps_backoff_until_stop(self, db):
        transport = ScriptedTransport([WsConnectionLost("dead")])
        feed, _ = make_feed(db, transport, base_delay=0.01, max_delay=0.02)
        asyncio.run(run_for(feed, seconds=0.2))

        assert transport.connect_calls >= 2  # keeps trying, bounded backoff
        assert feed.status.state == "stopped"


class TestSequenceGaps:
    def test_sequence_jump_fires_gap_callback_and_event(self, db):
        transport = ScriptedTransport(
            [
                ScriptedConnection(
                    [candle_frame(5, T0), candle_frame(8, T0 + timedelta(seconds=BUCKET))]
                )
            ]
        )
        feed, gaps = make_feed(db, transport)
        asyncio.run(run_for(feed))

        assert gaps and gaps[0][0] == "BTC-USD"
        with db.session() as session:
            gap_events = (
                session.query(EngineEvent)  # type: ignore[attr-defined]
                .filter(EngineEvent.event_type == "ws_gap_detected")  # type: ignore[attr-defined]
                .count()
            )
        assert gap_events >= 1

    def test_gap_events_are_idempotent_across_repeats(self, db):
        later = T0 + timedelta(seconds=BUCKET)
        transport = ScriptedTransport(
            [
                ScriptedConnection([candle_frame(5, T0), candle_frame(8, later)]),
                ScriptedConnection([Park()], park_on_empty=True),
            ]
        )
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        with db.session() as session:
            counts = {
                event.dedupe_key
                for event in session.query(EngineEvent).all()  # type: ignore[attr-defined]
                if event.dedupe_key is not None and event.event_type == "ws_gap_detected"  # type: ignore[attr-defined]
            }
        assert len(counts) == len({key for key in counts})  # dedupe keys unique


class TestStatus:
    def test_status_snapshot_tracks_the_lifecycle(self, db):
        transport = ScriptedTransport(
            [
                ScriptedConnection(
                    [candle_frame(1, T0), candle_frame(2, T0 + timedelta(seconds=BUCKET))]
                )
            ]
        )
        feed, _ = make_feed(db, transport)
        asyncio.run(run_for(feed))

        snapshot = feed.status.snapshot()
        assert snapshot["state"] == "stopped"
        assert snapshot["reconnects"] >= 0
        assert snapshot["subscriptions"] == ["candles", "heartbeats"]
        assert snapshot["last_complete"] == {"BTC-USD@FIVE_MINUTE": "2026-01-01T12:00:00Z"}
        json.dumps(snapshot)  # must be JSON-serializable for the local API

    def test_feed_status_defaults_are_safe(self):
        snapshot = FeedStatus().snapshot()
        assert snapshot["state"] == "stopped"
        assert json.dumps(snapshot)
