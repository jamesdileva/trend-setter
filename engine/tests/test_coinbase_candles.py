"""Offline tests for candle fetching: params, parsing, quarantine, backoff.

Roadmap Sprint 4 verification: rate-limit responses back off without
crashing (bounded attempts, Retry-After honored); invalid payloads are
quarantined; window guards reject oversized requests before any call.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from test_coinbase_client import KEY_NAME, ec_pem
from trendbot.exchange.coinbase_rest import (
    MAX_CANDLES_PER_REQUEST,
    CoinbaseRestClient,
    NetworkUnavailableError,
    RateLimitedError,
    fetch_public_candles,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW = timedelta(hours=10)


def wire_candle(
    start_unix: int, open_: int, high_: int, low_: int, close_: int, volume_: int
) -> dict[str, str]:
    return {
        "start": str(start_unix),
        "open": str(open_),
        "high": str(high_),
        "low": str(low_),
        "close": str(close_),
        "volume": str(volume_),
    }


def candles_payload(*entries: object) -> dict[str, object]:
    return {"candles": list(entries)}


def transport_recording(handler):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), calls


def make_client(transport: httpx.MockTransport) -> CoinbaseRestClient:
    return CoinbaseRestClient(key_name=KEY_NAME, private_key_pem=ec_pem(), transport=transport)


class TestAuthenticatedCandles:
    def test_window_is_fetched_with_verified_params_and_auth(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            entry = wire_candle(int(BASE.timestamp()) + 3600, 100, 110, 95, 105, 1)
            return httpx.Response(200, json=candles_payload(entry))

        transport, calls = transport_recording(handler)
        page = make_client(transport).get_candles("BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW)
        request = calls[0]
        assert request.url.path == "/api/v3/brokerage/products/BTC-USD/candles"
        assert request.url.params["granularity"] == "ONE_HOUR"
        assert request.url.params["limit"] == str(MAX_CANDLES_PER_REQUEST)
        assert request.url.params["start"] == str(int(BASE.timestamp()))
        assert request.url.params["end"] == str(int((BASE + WINDOW).timestamp()))
        assert request.headers["Authorization"].startswith("Bearer ")

        assert len(page.candles) == 1
        fetched = page.candles[0]
        assert fetched.product_id == "BTC-USD"
        assert fetched.granularity == "ONE_HOUR"
        assert fetched.start_time == datetime(2026, 1, 1, 1, tzinfo=UTC)
        assert fetched.open == Decimal("100")
        assert fetched.volume == Decimal("1")

    def test_wire_ordering_is_normalized_ascending(self):
        second = int(BASE.timestamp()) + 7200
        first = int(BASE.timestamp())
        third = int(BASE.timestamp()) + 3600
        payload = candles_payload(
            wire_candle(second, 1, 2, 0, 1, 1),
            wire_candle(first, 1, 2, 0, 1, 1),
            wire_candle(third, 1, 2, 0, 1, 1),
        )

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        page = make_client(httpx.MockTransport(handler)).get_candles(
            "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
        )
        starts = [candle.start_time for candle in page.candles]
        assert starts == sorted(starts)
        assert page.candles[0].start_time == BASE

    def test_unparseable_entries_are_quarantined(self):
        good = wire_candle(int(BASE.timestamp()), 100, 110, 95, 105, 1)
        bad_start = {
            "start": "not-a-number",
            "open": "1",
            "high": "2",
            "low": "0",
            "close": "1",
            "volume": "1",
        }
        bad_decimal = {
            "start": str(int(BASE.timestamp()) + 3600),
            "open": "abc",
            "high": "2",
            "low": "0",
            "close": "1",
            "volume": "1",
        }

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=candles_payload(good, bad_start, bad_decimal, "junk"))

        page = make_client(httpx.MockTransport(handler)).get_candles(
            "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
        )
        assert len(page.candles) == 1
        assert page.rejected_count == 3
        assert all(reason for reason in page.rejected_reasons)

    def test_ohlcv_violations_are_quarantined(self):
        inverted = wire_candle(int(BASE.timestamp()), 100, 90, 80, 105, 1)  # high < open

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=candles_payload(inverted))

        page = make_client(httpx.MockTransport(handler)).get_candles(
            "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
        )
        assert page.candles == []
        assert page.rejected_count == 1
        assert "high" in page.rejected_reasons[0]

    def test_window_larger_than_350_buckets_is_rejected_before_the_request(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("the network must not be called for an invalid window")

        client = make_client(httpx.MockTransport(handler))
        with pytest.raises(ValueError) as excinfo:
            client.get_candles(
                "BTC-USD", "ONE_MINUTE", BASE, BASE + timedelta(minutes=MAX_CANDLES_PER_REQUEST + 1)
            )
        assert str(MAX_CANDLES_PER_REQUEST) in str(excinfo.value)

    def test_naive_windows_are_rejected(self):
        transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"candles": []}))
        client = make_client(transport)
        with pytest.raises(ValueError):
            client.get_candles("BTC-USD", "ONE_HOUR", datetime(2026, 1, 1), BASE + WINDOW)


class TestPublicCandles:
    def test_public_path_sends_no_authorization_header(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            entry = wire_candle(int(BASE.timestamp()), 1, 2, 0, 1, 1)
            return httpx.Response(200, json=candles_payload(entry))

        transport, calls = transport_recording(handler)
        page = fetch_public_candles("ETH-USD", "ONE_HOUR", BASE, BASE + WINDOW, transport=transport)
        request = calls[0]
        assert request.url.path == "/api/v3/brokerage/market/products/ETH-USD/candles"
        assert "authorization" not in {key.lower() for key in request.headers}
        assert page.candles[0].product_id == "ETH-USD"


class TestRateLimitBackoff:
    def test_rate_limited_response_backs_off_and_retries(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(
            "trendbot.exchange.backoff.time.sleep",
            lambda seconds: sleeps.append(seconds),
        )
        attempts = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "rate"})
            return httpx.Response(200, json={"candles": []})

        page = make_client(httpx.MockTransport(handler)).get_candles(
            "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
        )
        assert attempts["count"] == 2
        assert page.candles == []
        assert sleeps and sleeps[0] >= 1  # Retry-After honored

    def test_exhausted_retries_raise_rate_limited_without_crashing_later(self, monkeypatch):
        monkeypatch.setattr("trendbot.exchange.backoff.time.sleep", lambda _seconds: None)
        attempts = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(429, json={"error": "rate"})

        with pytest.raises(RateLimitedError):
            make_client(httpx.MockTransport(handler)).get_candles(
                "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
            )
        assert attempts["count"] == 5  # bounded: MAX_ATTEMPTS, not infinite

    def test_network_errors_retry_then_succeed(self, monkeypatch):
        monkeypatch.setattr("trendbot.exchange.backoff.time.sleep", lambda _seconds: None)
        attempts = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ConnectError("flap")
            return httpx.Response(200, json={"candles": []})

        page = make_client(httpx.MockTransport(handler)).get_candles(
            "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
        )
        assert attempts["count"] == 3
        assert page.candles == []

    def test_non_retryable_classification_is_not_retried(self, monkeypatch):
        monkeypatch.setattr("trendbot.exchange.backoff.time.sleep", lambda _seconds: None)
        attempts = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(401, json={"error": "unauth"})

        with pytest.raises((Exception,)) as excinfo:
            make_client(httpx.MockTransport(handler)).get_candles(
                "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
            )
        assert attempts["count"] == 1
        assert excinfo.value.kind == "invalid_credentials"


class TestNetworkErrorsSurfaceTyped:
    def test_persistent_network_failure_raises_network_unavailable(self, monkeypatch):
        monkeypatch.setattr("trendbot.exchange.backoff.time.sleep", lambda _seconds: None)

        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        with pytest.raises(NetworkUnavailableError):
            make_client(httpx.MockTransport(handler)).get_candles(
                "BTC-USD", "ONE_HOUR", BASE, BASE + WINDOW
            )
