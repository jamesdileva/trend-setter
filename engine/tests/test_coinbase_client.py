"""Offline tests for Coinbase JWT construction and the validation client.

Uses a generated EC key (cryptography) and ``httpx.MockTransport`` fixtures
— no network, no real keys, and nothing trading-related beyond an empty
batch-cancel probe that cancels nothing (roadmap Sprint 3 verification:
no test places an order).
"""

from datetime import UTC, datetime

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from trendbot.exchange.coinbase_auth import (
    JWT_LIFETIME_SECONDS,
    JwtBuildError,
    build_rest_jwt,
    build_websocket_jwt,
)
from trendbot.exchange.coinbase_rest import (
    BATCH_CANCEL_PATH,
    CoinbaseRestClient,
    InsufficientPermissionsError,
    InvalidCredentialsError,
    NetworkUnavailableError,
    UnexpectedExchangeStateError,
)

KEY_NAME = (
    "organizations/11111111-2222-3333-4444-555555555555/"
    "apiKeys/66666666-7777-8888-9999-000000000000"
)
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
ACCOUNTS_PATH = "/api/v3/brokerage/accounts"


def ec_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def ed25519_pem() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


class TestJwtConstruction:
    def test_rest_jwt_matches_the_verified_spec(self):
        token = build_rest_jwt(
            KEY_NAME,
            ec_pem(),
            method="GET",
            host="api.coinbase.com",
            path=ACCOUNTS_PATH,
            now=FIXED_NOW,
        )
        header = pyjwt.get_unverified_header(token)
        claims = pyjwt.decode(token, options={"verify_signature": False})

        assert header["alg"] == "ES256"
        assert header["kid"] == KEY_NAME
        assert len(header["nonce"]) == 32
        assert all(char in "0123456789abcdef" for char in header["nonce"])
        assert claims["sub"] == KEY_NAME
        assert claims["iss"] == "cdp"
        assert claims["uri"] == f"GET api.coinbase.com{ACCOUNTS_PATH}"
        assert claims["exp"] - claims["nbf"] == JWT_LIFETIME_SECONDS == 120

    def test_rest_jwt_signature_verifies_with_the_public_key(self):
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        token = build_rest_jwt(
            KEY_NAME, pem, method="GET", host="api.coinbase.com", path="/x"
        )
        claims = pyjwt.decode(token, public_pem, algorithms=["ES256"])
        assert claims["sub"] == KEY_NAME

    def test_websocket_jwt_has_no_uri_claim(self):
        token = build_websocket_jwt(KEY_NAME, ec_pem(), now=FIXED_NOW)
        claims = pyjwt.decode(token, options={"verify_signature": False})
        assert "uri" not in claims
        assert claims["iss"] == "cdp"

    def test_ed25519_keys_are_rejected_with_plain_guidance(self):
        with pytest.raises(JwtBuildError) as excinfo:
            build_rest_jwt(
                KEY_NAME, ed25519_pem(), method="GET", host="h", path="/p"
            )
        assert "ECDSA" in str(excinfo.value)
        assert "Ed25519" in str(excinfo.value)


def stub_transport(
    accounts_status: int = 200,
    accounts_payload: object = None,
    cancel_status: int = 200,
    *,
    fail: bool = False,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("connection refused")
        if request.url.path.endswith("/accounts"):
            if isinstance(accounts_payload, str):
                return httpx.Response(accounts_status, text=accounts_payload)
            payload = accounts_payload if accounts_payload is not None else {"accounts": []}
            return httpx.Response(accounts_status, json=payload)
        if request.url.path.endswith(BATCH_CANCEL_PATH.rsplit("/", 1)[-1]):
            return httpx.Response(cancel_status, json={"results": []})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def make_client(
    pem: str | None = None,
    transport: httpx.MockTransport | None = None,
) -> CoinbaseRestClient:
    return CoinbaseRestClient(
        key_name=KEY_NAME,
        private_key_pem=pem or ec_pem(),
        transport=transport or stub_transport(),
    )


class TestValidationClient:
    def test_valid_credentials_pass_the_accounts_probe(self):
        client = make_client()
        assert client.validate_credentials() is True

    def test_sent_authorization_header_is_a_bearer_jwt(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"accounts": []})

        make_client(transport=httpx.MockTransport(handler)).validate_credentials()
        assert seen[0].headers["Authorization"].startswith("Bearer ")

    def test_http_401_is_invalid_credentials(self):
        with pytest.raises(InvalidCredentialsError):
            make_client(transport=stub_transport(accounts_status=401)).validate_credentials()

    def test_http_403_is_insufficient_permissions(self):
        with pytest.raises(InsufficientPermissionsError):
            make_client(transport=stub_transport(accounts_status=403)).validate_credentials()

    def test_http_500_is_unexpected_exchange_state(self):
        with pytest.raises(UnexpectedExchangeStateError):
            make_client(transport=stub_transport(accounts_status=500)).validate_credentials()

    def test_non_json_body_is_unexpected_exchange_state(self):
        with pytest.raises(UnexpectedExchangeStateError):
            make_client(
                transport=stub_transport(accounts_payload="<html>oops</html>")
            ).validate_credentials()

    def test_missing_accounts_key_is_unexpected_exchange_state(self):
        with pytest.raises(UnexpectedExchangeStateError):
            make_client(
                transport=stub_transport(accounts_payload={"nope": True})
            ).validate_credentials()

    def test_connection_failure_is_network_unavailable(self):
        with pytest.raises(NetworkUnavailableError):
            make_client(transport=stub_transport(fail=True)).validate_credentials()

    def test_ed25519_key_is_invalid_credentials_with_guidance(self):
        with pytest.raises(InvalidCredentialsError):
            make_client(pem=ed25519_pem()).validate_credentials()


class TestTradePermissionProbe:
    def test_reaching_the_cancel_endpoint_means_trade_permission(self):
        client = make_client(transport=stub_transport(cancel_status=200))
        assert client.detect_trade_permission() is True

    def test_validation_error_still_proves_trade_permission(self):
        client = make_client(transport=stub_transport(cancel_status=400))
        assert client.detect_trade_permission() is True

    def test_http_403_means_no_trade_permission(self):
        client = make_client(transport=stub_transport(cancel_status=403))
        assert client.detect_trade_permission() is False

    def test_rejected_credentials_make_the_probe_inconclusive(self):
        client = make_client(transport=stub_transport(cancel_status=401))
        assert client.detect_trade_permission() is None

    def test_network_failure_makes_the_probe_inconclusive(self):
        client = make_client(transport=stub_transport(fail=True))
        assert client.detect_trade_permission() is None
