"""Narrow Coinbase Advanced Trade REST client for credential validation.

This is the first slice of the Coinbase adapter (full adapter: Sprint 4
and Sprint 10). Only non-trading validation lives here:

- ``GET /api/v3/brokerage/accounts`` (view scope) — the non-trading
  credential probe (roadmap Sprint 3 task 7);
- ``POST /api/v3/brokerage/orders/batch_cancel`` with an empty id list —
  the trade-permission probe. It cancels nothing and places nothing; any
  non-403 outcome (including validation errors) proves the key reached a
  trade-scoped endpoint. Real-key behavior is confirmed manually by the
  user; the probe result is surfaced, never acted on for trading.

Errors are normalized into typed internal exceptions (implementation.md
§6) with plain-language messages for the wizard.
"""

from __future__ import annotations

import httpx

from trendbot.exchange.coinbase_auth import JwtBuildError, build_rest_jwt

REST_BASE_URL = "https://api.coinbase.com"
ACCOUNTS_PATH = "/api/v3/brokerage/accounts"
BATCH_CANCEL_PATH = "/api/v3/brokerage/orders/batch_cancel"
REQUEST_HOST = "api.coinbase.com"
TIMEOUT_SECONDS = 10.0


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
