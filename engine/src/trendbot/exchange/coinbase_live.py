"""Live Coinbase execution adapter (roadmap Sprint 10).

Implements the full `ExchangeAdapter` interface over the verified REST
endpoints. Every fact (order configurations, status enums, client_order_id
semantics, fills identity) is pinned to the Sprint 0 verification
(``docs/coinbase-verification-checklist.md``).

Safety rules (architecture.md §10):

- client_order_id travels on every order — duplicate protection is
  exchange-side (verified: reuse returns the existing order);
- a network failure after the request was sent raises
  :class:`UnknownOutcomeError` — the caller must reconcile, never blind-retry;
- 429s back off (rejected before processing, safe to retry);
- the adapter never touches fund-movement endpoints (guard-tested:
  the test forbids those route names in this module's source).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from trendbot.exchange.backoff import with_backoff
from trendbot.exchange.base import ExchangeAdapter, UnknownOutcomeError
from trendbot.exchange.coinbase_auth import JwtBuildError, build_rest_jwt
from trendbot.exchange.coinbase_rest import (
    InsufficientPermissionsError,
    InvalidCredentialsError,
    NetworkUnavailableError,
    RateLimitedError,
    UnexpectedExchangeStateError,
    _retry_after_seconds,
)
from trendbot.exchange.types import (
    AccountBalance,
    Fill,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderSnapshot,
    ProductInfo,
)
from trendbot.market_data.candles import Candle

STATUS_MAP: dict[str, str] = {
    "OPEN": "OPEN",
    "PENDING": "OPEN",
    "QUEUED": "OPEN",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELED",
    "CANCELED": "CANCELED",
    "EXPIRED": "CANCELED",
    "FAILED": "REJECTED",
    "UNKNOWN_ORDER_STATUS": "UNKNOWN",
}


def _now() -> datetime:
    return datetime.now(UTC)


class CoinbaseLiveExecutionAdapter(ExchangeAdapter):
    """Real Coinbase execution behind the ExchangeAdapter interface."""

    def __init__(
        self,
        *,
        key_name: str,
        private_key_pem: str,
        transport: httpx.BaseTransport | None = None,
        base_url: str = "https://api.coinbase.com",
        max_attempts: int = 4,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.key_name = key_name
        self.private_key_pem = private_key_pem
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.sleep = sleep

    def _headers(self, method: str, path: str) -> dict[str, str]:
        host = self.base_url.split("://", 1)[1]
        token = build_rest_jwt(
            self.key_name, self.private_key_pem, method=method, host=host, path=path
        )
        return {"Authorization": f"Bearer {token}"}

    def _call(
        self,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        def attempt() -> httpx.Response:
            try:
                with httpx.Client(
                    base_url=self.base_url,
                    transport=self.transport or httpx.HTTPTransport(),
                    timeout=10.0,
                ) as client:
                    return client.request(
                        method,
                        path,
                        headers=self._headers(method, path),
                        json=json_body,
                        params=params,
                    )
            except httpx.HTTPError as exc:
                raise NetworkUnavailableError() from exc
            except JwtBuildError as exc:
                raise InvalidCredentialsError() from exc

        return with_backoff(
            attempt,
            is_retryable=lambda exc: isinstance(exc, RateLimitedError),
            retry_after=lambda exc: getattr(exc, "retry_after", None),
            max_attempts=self.max_attempts,
            sleep=self.sleep or time.sleep,
        )

    def _check(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise RateLimitedError(retry_after=_retry_after_seconds(response))
        if response.status_code == 401:
            raise InvalidCredentialsError()
        if response.status_code == 403:
            raise InsufficientPermissionsError()
        if response.status_code != 200:
            raise UnexpectedExchangeStateError()

    # -- market data / accounts ---------------------------------------

    def test_connection(self) -> bool:
        response = self._call("GET", "/api/v3/brokerage/accounts", None)
        self._check(response)
        return True

    def get_accounts(self) -> list[AccountBalance]:
        response = self._call("GET", "/api/v3/brokerage/accounts", None)
        self._check(response)
        accounts: list[AccountBalance] = []
        for entry in response.json().get("accounts", []):
            accounts.append(
                AccountBalance(
                    currency=str(entry["currency"]),
                    available=Decimal(str(entry.get("available", "0"))),
                    hold=Decimal(str(entry.get("hold", "0"))),
                )
            )
        return accounts

    def get_product(self, product_id: str) -> ProductInfo:
        response = self._call(
            "GET", f"/api/v3/brokerage/products/{product_id}", None
        )
        self._check(response)
        p = response.json()
        return ProductInfo(
            product_id=str(p["product_id"]),
            base_increment=Decimal(str(p["base_increment"])),
            quote_increment=Decimal(str(p["quote_increment"])),
            price_increment=Decimal(str(p.get("price_increment") or p["quote_increment"])),
            base_min_size=Decimal(str(p["base_min_size"])),
            base_max_size=Decimal(str(p["base_max_size"])),
            quote_min_size=Decimal(str(p["quote_min_size"])),
            quote_max_size=Decimal(str(p["quote_max_size"])),
            limit_only=bool(p.get("limit_only", False)),
            post_only=bool(p.get("post_only", False)),
            cancel_only=bool(p.get("cancel_only", False)),
            trading_disabled=bool(p.get("trading_disabled", False)),
        )

    def get_historical_candles(
        self, product_id: str, granularity: str, start: datetime, end: datetime
    ) -> list[Candle]:
        label = granularity
        from trendbot.market_data.granularity import granularity_seconds

        seconds = granularity_seconds(label)
        candles: list[Candle] = []
        window = timedelta(seconds=350 * seconds)
        current = start
        while current < end:
            w_end = min(current + window, end)
            params = {
                "start": str(int(current.timestamp())),
                "end": str(int(w_end.timestamp())),
                "limit": "350",
                "granularity": label,
            }
            response = self._call(
                "GET",
                f"/api/v3/brokerage/products/{product_id}/candles",
                None,
                params=params,
            )
            self._check(response)
            for entry in response.json().get("candles", []):
                candle = self._parse_candle(entry, product_id, label)
                if candle is not None:
                    candles.append(candle)
            current = w_end
        candles.sort(key=lambda candle: candle.start_time)
        return candles

    @staticmethod
    def _parse_candle(entry: dict[str, object], product_id: str, granularity: str) -> Candle | None:
        try:
            start_unix = int(str(entry["start"]))
            return Candle(
                product_id=product_id,
                granularity=granularity,
                start_time=datetime.fromtimestamp(start_unix, tz=UTC),
                open=Decimal(str(entry["open"])),
                high=Decimal(str(entry["high"])),
                low=Decimal(str(entry["low"])),
                close=Decimal(str(entry["close"])),
                volume=Decimal(str(entry["volume"])),
                is_complete=True,
            )
        except (KeyError, ValueError, InvalidOperation):
            return None

    # -- orders --------------------------------------------------------

    def create_order(self, request: OrderRequest) -> OrderResult:
        if request.limit_price is not None:
            configuration: dict[str, object] = {
                "limit_limit_gtc": {
                    "base_size": str(request.base_size or request.quote_size or "0"),
                    "limit_price": str(request.limit_price),
                    "post_only": False,
                }
            }
        else:
            configuration = {
                "market_market_ioc": {"base_size": str(request.base_size or "0")}
            }
        body: dict[str, object] = {
            "client_order_id": request.client_order_id,
            "product_id": request.product_id,
            "side": request.side.value.upper(),
            "order_configuration": configuration,
        }
        try:
            response = self._call("POST", "/api/v3/brokerage/orders", body)
        except NetworkUnavailableError:
            # The request may or may not have been received — the outcome is
            # unknowable and must be reconciled, never retried blindly.
            raise UnknownOutcomeError(request.client_order_id) from None
        self._check(response)
        payload = response.json()
        if payload.get("success"):
            success = payload.get("success_response", {})
            return OrderResult(
                client_order_id=request.client_order_id,
                exchange_order_id=(
                    str(success["order_id"]) if success.get("order_id") else None
                ),
                accepted=True,
            )
        error = payload.get("error_response", {})
        reason = str(error.get("failure_reason") or error.get("message") or "unknown")
        return OrderResult(
            client_order_id=request.client_order_id,
            exchange_order_id=None,
            accepted=False,
            failure_reason=reason,
        )

    def get_order(self, exchange_order_id: str) -> OrderSnapshot | None:
        response = self._call(
            "GET",
            f"/api/v3/brokerage/orders/historical/{exchange_order_id}",
            None,
        )
        self._check(response)
        order = response.json().get("order")
        if not isinstance(order, dict):
            return None
        return self._parse_snapshot(order)

    def list_open_orders(self, product_id: str | None = None) -> list[OrderSnapshot]:
        params: dict[str, str] = {"status": "OPEN"}
        if product_id:
            params["product_id"] = product_id
        response = self._call(
            "GET", "/api/v3/brokerage/orders/historical/batch", None, params=params
        )
        self._check(response)
        snapshots: list[OrderSnapshot] = []
        for order in response.json().get("orders", []):
            if not isinstance(order, dict):
                continue
            if str(order.get("status", "")) != "OPEN":
                continue
            snapshot = self._parse_snapshot(order)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    def list_fills(self, product_id: str | None = None) -> list[Fill]:
        fills: list[Fill] = []
        cursor: str | None = None
        for _ in range(20):  # bounded pagination
            params: dict[str, str] = {"limit": "100"}
            if product_id:
                params["product_ids"] = product_id
            if cursor:
                params["cursor"] = cursor
            response = self._call(
                "GET", "/api/v3/brokerage/orders/historical/fills", None, params=params
            )
            self._check(response)
            payload = response.json()
            for entry in payload.get("fills", []):
                parsed = self._parse_fill(entry)
                if parsed is not None:
                    fills.append(parsed)
            cursor = payload.get("cursor")
            if not cursor:
                break
        return fills

    @staticmethod
    def _parse_fill(entry: dict[str, object]) -> Fill | None:
        try:
            trade_time_raw = str(entry["trade_time"])
            trade_time = datetime.fromisoformat(trade_time_raw.replace("Z", "+00:00"))
            side_raw = str(entry.get("side", "BUY")).upper()
            return Fill(
                exchange_order_id=str(entry["order_id"]),
                trade_id=str(entry["trade_id"]),
                product_id=str(entry["product_id"]),
                side=OrderSide.BUY if side_raw == "BUY" else OrderSide.SELL,
                price=Decimal(str(entry["price"])),
                size=Decimal(str(entry["size"])),
                commission=Decimal(str(entry.get("commission", "0"))),
                trade_time=trade_time,
            )
        except (KeyError, ValueError, InvalidOperation):
            return None

    @staticmethod
    def _parse_snapshot(order: dict[str, object]) -> OrderSnapshot | None:
        try:
            return OrderSnapshot(
                exchange_order_id=str(order["order_id"]),
                client_order_id=str(order.get("client_order_id", "")),
                product_id=str(order["product_id"]),
                side=OrderSide(str(order.get("side", "BUY")).lower()),
                status=STATUS_MAP.get(str(order.get("status", "")), "UNKNOWN"),
                filled_size=Decimal(str(order.get("filled_size", "0"))),
                total_fees=Decimal(str(order.get("total_fees", "0"))),
            )
        except (KeyError, ValueError, InvalidOperation):
            return None

    def cancel_order(self, exchange_order_id: str) -> bool:
        response = self._call(
            "POST", "/api/v3/brokerage/orders/batch_cancel", {"order_ids": [exchange_order_id]}
        )
        self._check(response)
        for entry in response.json().get("results", []):
            if entry.get("order_id") == exchange_order_id:
                return bool(entry.get("success"))
        return False
