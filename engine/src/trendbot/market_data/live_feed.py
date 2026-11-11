"""Live candle feed: subscription, completeness, reconnect, gaps (Sprint 5).

Operational rules verified in Sprint 0 (checklist item 3) that this
implements:

- Subscribe **immediately** after connecting — the server disconnects if
  no subscribe arrives within 5 seconds; one channel per subscription
  message (``candles`` and ``heartbeats`` separately).
- Heartbeats are mandatory: idle channels close after 60–90 s, and the
  feed treats silence longer than ``stale_after`` seconds as a lost
  connection and forces a reconnect. Market-data channels are public
  (no JWT) and rate-limited at 8 connections/second per IP — reconnects
  back off exponentially with jitter.

Completeness: the wire sends the in-progress candle (~1 s cadence) with
no closed flag. A bucket is complete when a later event shows a newer
bucket start; only completed candles are persisted, deduplicated both by
last-stored tracking and the unique candle key — incomplete data never
reaches the persisted signal path (roadmap Sprint 5 verification).

Sequence jumps and disconnects emit gap callbacks (with ranges) so the
REST backfiller can repair history; every gap is also recorded as an
idempotent engine event.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from trendbot.database.repositories import CandleRepository, EngineEventRepository
from trendbot.market_data.candles import Candle
from trendbot.market_data.granularity import granularity_for_timeframe, granularity_seconds
from trendbot.market_data.ws_events import (
    CandleEvent,
    HeartbeatEvent,
    IgnoredMessage,
    NormalizedEvent,
    normalize_message,
)
from trendbot.market_data.ws_transport import TransportFactory, WsConnection, WsConnectionLost

PUBLIC_WS_URL = "wss://advanced-trade-ws.coinbase.com"
STALE_AFTER_SECONDS = 15.0
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
CONNECTION_RESET_SECONDS = 60.0


@dataclass
class FeedStatus:
    """Live connection health, exposed through the local API."""

    state: str = "stopped"  # connecting | connected | reconnecting | stopped
    connected_since: datetime | None = None
    last_message_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    reconnects: int = 0
    subscriptions: list[str] = field(default_factory=list)
    last_complete: dict[str, str] = field(default_factory=dict)
    last_error: str | None = None
    ignored_frames: int = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self.state,
            "connected_since": _iso(self.connected_since),
            "last_message_at": _iso(self.last_message_at),
            "last_heartbeat_at": _iso(self.last_heartbeat_at),
            "reconnects": self.reconnects,
            "subscriptions": list(self.subscriptions),
            "last_complete": dict(self.last_complete),
            "last_error": self.last_error,
            "ignored_frames": self.ignored_frames,
        }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%SZ")


class CandleFeed:
    """Owns the live candle stream: connect, consume, persist, reconnect."""

    def __init__(
        self,
        *,
        url: str,
        product_ids: list[str],
        timeframe: str = "5m",
        granularity: str | None = None,
        transport_factory: TransportFactory,
        repository: CandleRepository,
        events: EngineEventRepository | None = None,
        status: FeedStatus | None = None,
        on_gap: Callable[[str, str, datetime, datetime], Awaitable[None]] | None = None,
        stale_after: float = STALE_AFTER_SECONDS,
        base_delay: float = RECONNECT_BASE_DELAY,
        max_delay: float = RECONNECT_MAX_DELAY,
    ) -> None:
        self.url = url
        self.product_ids = list(product_ids)
        self.timeframe = timeframe
        self.granularity = granularity or granularity_for_timeframe(timeframe)
        self._transport_factory = transport_factory
        self._repo = repository
        self._events = events
        self.status = status or FeedStatus()
        self._on_gap = on_gap  # async (product_id, timeframe, gap_start, gap_end)
        self.stale_after = stale_after
        self.base_delay = base_delay
        self.max_delay = max_delay

        self._pending: dict[tuple[str, str], Candle] = {}
        self._last_stored_start: dict[tuple[str, str], datetime] = {}
        self._last_sequence: dict[str, int] = {}
        self._stop_requested = False
        self._current_connection: WsConnection | None = None
        self._connected_at: datetime | None = None
        self._consecutive_failures = 0
        self._gap_keys: set[str] = set()

    async def run(self) -> None:
        """Run until :meth:`stop`. Reconnects forever with bounded backoff."""
        self.status.state = "connecting"
        while not self._stop_requested:
            connection: WsConnection | None = None
            try:
                connection = await self._transport_factory()
                self._current_connection = connection
                await self._subscribe(connection)
                self._on_connected()
                await self._consume(connection)
            except WsConnectionLost as exc:
                if not self._stop_requested:
                    self._note_disconnect(str(exc))
            except TimeoutError:
                if not self._stop_requested:
                    self._note_disconnect(
                        f"no messages for {self.stale_after:.1f}s (silence exceeded) — reconnecting"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - feed must survive anything
                if not self._stop_requested:
                    self._note_disconnect(f"unexpected feed error: {exc}")
            finally:
                self._current_connection = None
                if connection is not None:
                    try:
                        await connection.close()
                    except Exception:  # noqa: BLE001 - close is best effort
                        pass
            if self._stop_requested:
                break
            await self._sleep_before_reconnect()
            self.status.state = "reconnecting"
        self.status.state = "stopped"

    async def stop(self) -> None:
        """Request shutdown; closes the current connection to unblock recv."""
        self._stop_requested = True
        connection = self._current_connection
        if connection is not None:
            try:
                await connection.close()
            except Exception:  # noqa: BLE001 - best effort
                pass

    async def _subscribe(self, connection: WsConnection) -> None:
        # Verified: subscribe immediately (5s deadline), one channel per message.
        await connection.send(
            json.dumps(
                {"type": "subscribe", "channel": "candles", "product_ids": self.product_ids}
            )
        )
        await connection.send(
            json.dumps({"type": "subscribe", "channel": "heartbeats"})
        )
        self.status.subscriptions = ["candles", "heartbeats"]

    def _on_connected(self) -> None:
        now = datetime.now(UTC)
        self.status.state = "connected"
        self.status.connected_since = now
        self.status.last_error = None
        self._connected_at = now

    def _note_disconnect(self, detail: str) -> None:
        now = datetime.now(UTC)
        if (
            self._connected_at is not None
            and (now - self._connected_at).total_seconds() >= CONNECTION_RESET_SECONDS
        ):
            self._consecutive_failures = 0
        self._connected_at = None
        self.status.reconnects += 1
        self.status.last_error = detail
        self.status.state = "reconnecting"
        self._record_event("ws_disconnected", detail, dedupe_key=None)
        self._fire_gaps(now)

    def _fire_gaps(self, now: datetime) -> None:
        """Emit backfill ranges for the missed period after a disconnect."""
        seconds = granularity_seconds(self.granularity)
        for product_id in self.product_ids:
            key = (product_id, self.granularity)
            last_stored = self._last_stored_start.get(key)
            if last_stored is not None:
                gap_start = last_stored + timedelta(seconds=seconds)
            else:
                gap_start = now - timedelta(seconds=2 * seconds)
            if now > gap_start:
                self._emit_gap(product_id, gap_start, now)

    def _emit_gap(self, product_id: str, gap_start: datetime, gap_end: datetime) -> None:
        dedupe_key = f"ws-gap-{product_id}-{self.granularity}-{int(gap_start.timestamp())}"
        if dedupe_key in self._gap_keys:
            return
        self._gap_keys.add(dedupe_key)
        self._record_event(
            "ws_gap_detected",
            f"Gap detected for {product_id} ({self.timeframe}); scheduling REST backfill.",
            dedupe_key=dedupe_key,
        )
        if self._on_gap is None:
            return

        async def run_gap() -> None:
            try:
                await self._on_gap(product_id, self.timeframe, gap_start, gap_end)  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001 - backfill failure must not kill the feed
                self._record_event(
                    "ws_backfill_failed",
                    f"Backfill failed for {product_id}: {exc}",
                    dedupe_key=f"{dedupe_key}-failed-{uuid.uuid4().hex[:8]}",
                )

        asyncio.get_running_loop().create_task(run_gap())

    async def _consume(self, connection: WsConnection) -> None:
        while not self._stop_requested:
            raw = await asyncio.wait_for(connection.recv(), timeout=self.stale_after)
            for event in normalize_message(raw, default_granularity=self.granularity):
                self._handle(event)

    def _handle(self, event: NormalizedEvent) -> None:
        if isinstance(event, IgnoredMessage):
            self.status.ignored_frames += 1
            return
        if isinstance(event, HeartbeatEvent):
            self.status.last_heartbeat_at = event.received_at
            self.status.last_message_at = event.received_at
            self._track_sequence("heartbeats", event.sequence_num)
            return
        if isinstance(event, CandleEvent):
            self.status.last_message_at = event.received_at
            channel = f"candles:{event.candle.product_id}"
            if self._check_sequence(channel, event.sequence_num):
                seconds = granularity_seconds(self.granularity)
                self._emit_gap(
                    event.candle.product_id,
                    datetime.now(UTC) - timedelta(seconds=2 * seconds),
                    datetime.now(UTC),
                )
            self._handle_candle(event)
        # SubscriptionAck: status already reflects the subscriptions.

    def _check_sequence(self, channel: str, sequence_num: int | None) -> bool:
        """Track per-channel sequence numbers; True when a jump (gap) is found."""
        if sequence_num is None:
            return False
        last = self._last_sequence.get(channel)
        self._last_sequence[channel] = max(sequence_num, last) if last is not None else sequence_num
        return last is not None and sequence_num > last + 1

    def _handle_candle(self, event: CandleEvent) -> None:
        candle = event.candle
        key = (candle.product_id, candle.granularity)
        previous = self._pending.get(key)
        if previous is not None and candle.start_time > previous.start_time:
            self._store_completed(previous)
        if previous is None or candle.start_time >= previous.start_time:
            self._pending[key] = candle
        # Older-than-pending candles are stale duplicates after reconnect snapshots.

    def _store_completed(self, candle: Candle) -> None:
        key = (candle.product_id, candle.granularity)
        last_stored = self._last_stored_start.get(key)
        if last_stored is not None and candle.start_time <= last_stored:
            return  # duplicate — already persisted for this bucket
        completed = replace(candle, is_complete=True)
        self._repo.upsert_many([completed])
        self._last_stored_start[key] = candle.start_time
        self.status.last_complete[f"{key[0]}@{key[1]}"] = _iso(candle.start_time) or ""

    def _track_sequence(self, channel: str, sequence_num: int | None) -> None:
        self._check_sequence(channel, sequence_num)

    async def _sleep_before_reconnect(self) -> None:
        delay = min(
            self.base_delay * (2 ** self._consecutive_failures), self.max_delay
        )
        self._consecutive_failures += 1
        await asyncio.sleep(delay + random.uniform(0, 0.25 * delay))

    def _record_event(
        self, event_type: str, message: str, *, dedupe_key: str | None
    ) -> None:
        if self._events is None:
            return
        try:
            self._events.append(
                event_type=event_type,
                component="market_data",
                message=message,
                dedupe_key=dedupe_key,
            )
        except Exception:  # noqa: BLE001 - event logging must not kill the feed
            pass
