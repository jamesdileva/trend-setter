"""Narrow Coinbase Advanced Trade REST client: validation and candle reads.

This is the growing Coinbase adapter (full adapter: Sprint 10). It keeps
to read-only, non-trading calls:

- ``GET /api/v3/brokerage/accounts`` (view scope) — the non-trading
  credential probe (roadmap Sprint 3 task 7);
- ``POST /api/v3/brokerage/orders/batch_cancel`` with an empty id list —
  the trade-permission probe. It cancels nothing and places nothing; any
  non-403 outcome (including validation errors) proves the key reached a
  trade-scoped endpoint. Real-key behavior is confirmed manually by the
  user; the probe result is surfaced, never acted on for trading.
- ``GET .../products/{id}/candles`` (view scope) and the unauthenticated
  ``/market/...`` public variant — historical candle windows (Sprint 4),
  with bounded backoff on rate limits and network errors.

Errors are normalized into typed internal exceptions (implementation.md
§6) with plain-language messages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from trendbot.exchange.backoff import with_backoff
from trendbot.exchange.coinbase_auth import JwtBuildError, build_rest_jwt
from trendbot.market_data.candles import Candle
from trendbot.market_data.granularity import granularity_seconds

REST_BASE_URL = "https://api.coinbase.com"
ACCOUNTS_PATH = "/api/v3/brokerage/accounts"
BATCH_CANCEL_PATH = "/api/v3/brokerage/orders/batch_cancel"
CANDLES_PATH_TEMPLATE = "/api/v3/brokerage/products/{product_id}/candles"
PUBLIC_CANDLES_PATH_TEMPLATE = "/api/v3/brokerage/market/products/{product_id}/candles"
REQUEST_HOST = "api.coinbase.com"
TIMEOUT_SECONDS = 10.0

# Verified limit (Sprint 0, checklist item 4): "By default, returns 350 (max 350)."
MAX_CANDLES_PER_REQUEST = 350


class CoinbaseValidationError(Exception):
    """Base for classified credential-validation failures."""

    kind = "unexpected_exchange_state"
    message = "The connection check ended in an unexpected state. Try again."


class InvalidCredentialsError(CoinbaseValidationError):
    kind = "invalid_credentials"
    message = (
        "Coinbase rejected this key. Check that the key name and private key were copied "
        "exactly, and that the key was created as an ECDSA (ES256) key — Ed25519 keys do "
        "not work here."
    )


class InsufficientPermissionsError(CoinbaseValidationError):
    kind = "insufficient_permissions"
    message = (
        "The key reached Coinbase but is missing the View permission. Re-create the key "
        "with View selected. Never select Transfer."
    )


class NetworkUnavailableError(CoinbaseValidationError):
    kind = "network_unavailable"
    message = "Could not reach Coinbase. Check your internet connection and try again."


class UnexpectedExchangeStateError(CoinbaseValidationError):
    kind = "unexpected_exchange_state"
    message = "The connection check ended in an unexpected state. Try again."


class RateLimitedError(CoinbaseValidationError):
    kind = "rate_limited"
    message = (
        "Coinbase is rate limiting requests. Requests slow down and retry "
        "automatically with backoff."
    )

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(self.message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class CandlePage:
    """One fetched candle window: validated candles plus quarantine count."""

    candles: list[Candle] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_reasons)


def _default_transport() -> httpx.BaseTransport:
    return httpx.HTTPTransport()


class CoinbaseRestClient:
    """Performs authenticated, non-trading REST calls for validation."""

    def __init__(
        self,
        *,
        key_name: str,
        private_key_pem: str,
        transport: httpx.BaseTransport | None = None,
        base_url: str = REST_BASE_URL,
    ) -> None:
        self.key_name = key_name
        self.private_key_pem = private_key_pem
        self.base_url = base_url.rstrip("/")
        self._transport = transport or _default_transport()

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        host = self.base_url.split("://", 1)[1]
        token = build_rest_jwt(
            self.key_name,
            self.private_key_pem,
            method=method,
            host=host,
            path=path,
        )
        return {"Authorization": f"Bearer {token}"}

    def _request(
        self, method: str, path: str, json_body: dict[str, object] | None = None
    ) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self.base_url,
                transport=self._transport,
                timeout=TIMEOUT_SECONDS,
            ) as client:
                return client.request(
                    method,
                    path,
                    headers=self._auth_headers(method, path),
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise NetworkUnavailableError() from exc
        except JwtBuildError as exc:
            raise InvalidCredentialsError() from exc

    def validate_credentials(self) -> bool:
        """Run the non-trading accounts probe. True = key valid with view access.

        Raises the classified :class:`CoinbaseValidationError` subclasses on
        failure — callers surface ``kind``/``message`` to the wizard.
        """
        response = self._request("GET", ACCOUNTS_PATH)
        if response.status_code == 401:
            raise InvalidCredentialsError()
        if response.status_code == 403:
            raise InsufficientPermissionsError()
        if response.status_code != 200:
            raise UnexpectedExchangeStateError()
        try:
            payload = response.json()
        except ValueError as exc:
            raise UnexpectedExchangeStateError() from exc
        if not isinstance(payload, dict) or "accounts" not in payload:
            raise UnexpectedExchangeStateError()
        return True

    def detect_trade_permission(self) -> bool | None:
        """Probe trade scope with an empty batch-cancel (cancels nothing).

        Returns True when the key reaches a trade-scoped endpoint, False on
        an explicit 403, and None when the outcome is inconclusive.
        """
        try:
            response = self._request("POST", BATCH_CANCEL_PATH, {"order_ids": []})
        except InvalidCredentialsError:
            return None
        except (NetworkUnavailableError, UnexpectedExchangeStateError):
            return None
        if response.status_code == 401:
            # Credentials rejected outright: the probe says nothing about trade scope.
            return None
        if response.status_code == 403:
            return False
        return True

    def get_candles(
        self, product_id: str, granularity: str, start: datetime, end: datetime
    ) -> CandlePage:
        """Fetch one authenticated candle window (view scope), with backoff.

        ``[start, end)`` must span at most ``MAX_CANDLES_PER_REQUEST``
        buckets; the importer pages windows. Retryable failures (rate
        limits, network) back off per the verified guidance.
        """
        path = CANDLES_PATH_TEMPLATE.format(product_id=product_id)
        return _fetch_candles(
            path,
            _candle_params(granularity, start, end),
            headers=self._auth_headers("GET", path),
            transport=self._transport,
            base_url=self.base_url,
            product_id=product_id,
            granularity=granularity,
        )


def _candle_params(granularity: str, start: datetime, end: datetime) -> dict[str, str]:
    """Build the verified candle request parameters for ``[start, end)``.

    Wire-format note (flagged in the Sprint 0 checklist, item 7): the
    documented schema shows granularity enum labels; ``start``/``end`` are
    UNIX seconds as strings. This is confirmed against the live public API
    during this sprint's verification.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Candle windows require timezone-aware UTC datetimes.")
    if end <= start:
        raise ValueError("The candle window end must be after its start.")
    seconds = granularity_seconds(granularity)
    if (end - start) > timedelta(seconds=MAX_CANDLES_PER_REQUEST * seconds):
        raise ValueError(
            f"Candle windows span at most {MAX_CANDLES_PER_REQUEST} {granularity} buckets; "
            "page the import in smaller windows."
        )
    return {
        "start": str(int(start.astimezone(UTC).timestamp())),
        "end": str(int(end.astimezone(UTC).timestamp())),
        "limit": str(MAX_CANDLES_PER_REQUEST),
        "granularity": granularity,
    }


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_candle_page(payload: object, product_id: str, granularity: str) -> CandlePage:
    """Parse a candles payload; invalid entries are quarantined, never stored.

    The wire payload does not repeat product/granularity per candle (they
    are implicit in the request), so the requested context is stamped on
    each parsed candle.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("candles"), list):
        raise UnexpectedExchangeStateError()
    candles: list[Candle] = []
    rejected: list[str] = []
    for entry in payload["candles"]:
        if not isinstance(entry, dict):
            rejected.append("entry is not an object")
            continue
        try:
            start_unix = int(str(entry["start"]))
            start_time = datetime.fromtimestamp(start_unix, tz=UTC)
            values = {
                name: Decimal(str(entry[name]))
                for name in ("open", "high", "low", "close", "volume")
            }
        except (KeyError, ValueError, InvalidOperation) as exc:
            rejected.append(f"unparseable candle entry: {exc}")
            continue
        candle = Candle(
            product_id=product_id,
            granularity=granularity,
            start_time=start_time,
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            volume=values["volume"],
            is_complete=True,
        )
        problems = candle.validate()
        if problems:
            rejected.append(" ".join(problems))
            continue
        candles.append(candle)
    # Wire ordering is not documented; normalize to ascending time.
    candles.sort(key=lambda candle: candle.start_time)
    return CandlePage(candles=candles, rejected_reasons=rejected)


def _fetch_candles(
    path: str,
    params: dict[str, str],
    *,
    headers: dict[str, str] | None,
    transport: httpx.BaseTransport | None,
    base_url: str,
    product_id: str,
    granularity: str,
    max_attempts: int = 5,
    sleep: Callable[[float], None] | None = None,
) -> CandlePage:
    """Fetch and parse one candle window with bounded backoff on retryables."""

    def attempt() -> CandlePage:
        try:
            with httpx.Client(
                base_url=base_url,
                transport=transport or _default_transport(),
                timeout=TIMEOUT_SECONDS,
            ) as client:
                response = client.request("GET", path, headers=headers or {}, params=params)
        except httpx.HTTPError as exc:
            raise NetworkUnavailableError() from exc
        if response.status_code == 429:
            raise RateLimitedError(retry_after=_retry_after_seconds(response))
        if response.status_code == 401:
            raise InvalidCredentialsError()
        if response.status_code == 403:
            raise InsufficientPermissionsError()
        if response.status_code != 200:
            raise UnexpectedExchangeStateError()
        try:
            payload = response.json()
        except ValueError as exc:
            raise UnexpectedExchangeStateError() from exc
        return _parse_candle_page(payload, product_id, granularity)

    return with_backoff(
        attempt,
        is_retryable=lambda exc: isinstance(exc, (RateLimitedError, NetworkUnavailableError)),
        retry_after=lambda exc: getattr(exc, "retry_after", None),
        max_attempts=max_attempts,
        sleep=sleep,
    )


def fetch_public_candles(
    product_id: str,
    granularity: str,
    start: datetime,
    end: datetime,
    *,
    transport: httpx.BaseTransport | None = None,
    base_url: str = REST_BASE_URL,
) -> CandlePage:
    """Fetch candles from the verified public (unauthenticated) family.

    Paper/backtest mode works without any API key through this path
    (``/api/v3/brokerage/market/...`` — Sprint 0, checklist item 3).
    """
    path = PUBLIC_CANDLES_PATH_TEMPLATE.format(product_id=product_id)
    return _fetch_candles(
        path,
        _candle_params(granularity, start, end),
        headers=None,
        transport=transport,
        base_url=base_url,
        product_id=product_id,
        granularity=granularity,
    )
