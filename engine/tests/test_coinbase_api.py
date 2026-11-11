"""End-to-end offline tests for the connection endpoints (roadmap Sprint 3).

Covers the verification bullets: invalid keys fail with actionable
messages, a valid (mocked) read-only key passes, trade permission is
detected separately, the secret never appears in SQLite or API responses,
and disconnect removes both the secret and the reference. No test places
an order — the only trading-path call is an empty batch-cancel probe that
cancels nothing.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from trendbot.api.app import create_app
from trendbot.application.coinbase_connection import SECRET_KEY
from trendbot.database import Database, upgrade_to_head
from trendbot.security.secret_store import InMemorySecretStore

KEY_NAME = (
    "organizations/11111111-2222-3333-4444-555555555555/"
    "apiKeys/66666666-7777-8888-9999-000000000000"
)


def ec_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def ed25519_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


class StubRoutes:
    """Mutable Coinbase response stubs shared with the app under test."""

    def __init__(self) -> None:
        self.accounts_status = 200
        self.accounts_payload: object = {"accounts": [{"uuid": "u-1", "currency": "USD"}]}
        self.cancel_status = 200
        self.fail = False

    def transport(self) -> httpx.MockTransport:
        stub = self

        def handler(request: httpx.Request) -> httpx.Response:
            if stub.fail:
                raise httpx.ConnectError("connection refused")
            if request.url.path.endswith("/accounts"):
                if isinstance(stub.accounts_payload, str):
                    return httpx.Response(stub.accounts_status, text=stub.accounts_payload)
                return httpx.Response(stub.accounts_status, json=stub.accounts_payload)
            if request.url.path.endswith("/batch_cancel"):
                return httpx.Response(stub.cancel_status, json={"results": []})
            return httpx.Response(404, json={})

        return httpx.MockTransport(handler)


@pytest.fixture()
def stub_routes() -> StubRoutes:
    return StubRoutes()


@pytest.fixture()
def env(tmp_path, stub_routes):
    database = Database(tmp_path / "coinbase.db")
    upgrade_to_head(database)
    secret_store = InMemorySecretStore()
    client = TestClient(
        create_app(
            "s3cret",
            database=database,
            secret_store=secret_store,
            coinbase_transport=stub_routes.transport(),
        ),
        client=("127.0.0.1", 51000),
    )
    return {
        "client": client,
        "database": database,
        "secrets": secret_store,
        "stub": stub_routes,
        "tmp_path": tmp_path,
    }


def connect(client: TestClient, key_name: str = KEY_NAME, pem: str | None = None):
    return client.post(
        "/coinbase/credentials",
        headers={"X-Local-Token": "s3cret"},
        json={"key_name": key_name, "private_key_pem": pem or ec_pem()},
    )


class TestConnect:
    def test_valid_key_is_stored_and_validated(self, env):
        response = connect(env["client"])
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "valid"
        assert body["permissions"] == "view+trade"
        assert body["trade_permission"] is True
        # Secret lives in the OS store, never in the database.
        assert env["secrets"].get_secret(SECRET_KEY).startswith("-----BEGIN")

    def test_secret_never_reaches_sqlite_at_byte_level(self, env):
        connect(env["client"])
        raw = env["database"].path.read_bytes()
        assert b"BEGIN EC PRIVATE" not in raw
        assert b"BEGIN PRIVATE KEY" not in raw

    def test_invalid_key_fails_with_actionable_message(self, env):
        env["stub"].accounts_status = 401
        response = connect(env["client"])
        assert response.status_code == 400
        body = response.json()
        assert body["status"] == "invalid_credentials"
        assert "exactly" in body["message"]
        assert "ECDSA" in body["message"]
        assert env["secrets"].get_secret(SECRET_KEY) is None

    def test_missing_view_permission_is_classified(self, env):
        env["stub"].accounts_status = 403
        response = connect(env["client"])
        assert response.status_code == 400
        body = response.json()
        assert body["status"] == "insufficient_permissions"
        assert "View" in body["message"]
        assert "Transfer" in body["message"]

    def test_network_failure_is_classified(self, env):
        env["stub"].fail = True
        response = connect(env["client"])
        assert response.status_code == 400
        body = response.json()
        assert body["status"] == "network_unavailable"
        assert "internet connection" in body["message"]

    def test_unexpected_response_is_classified(self, env):
        env["stub"].accounts_payload = "<html>gateway</html>"
        response = connect(env["client"])
        assert response.status_code == 400
        assert response.json()["status"] == "unexpected_exchange_state"

    def test_ed25519_key_is_rejected_with_ecdsa_guidance(self, env):
        response = connect(env["client"], pem=ed25519_pem())
        assert response.status_code == 400
        body = response.json()
        assert body["status"] == "invalid_credentials"
        assert "Ed25519" in body["message"]

    def test_trade_permission_absent_is_reported_separately(self, env):
        env["stub"].cancel_status = 403
        response = connect(env["client"])
        assert response.status_code == 200
        body = response.json()
        assert body["permissions"] == "view"
        assert body["trade_permission"] is False


class TestStatusAndDiagnostics:
    def test_status_before_connecting_is_disconnected(self, env):
        response = env["client"].get(
            "/coinbase/connection", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 200
        assert response.json()["connected"] is False

    def test_status_after_connecting_never_carries_the_secret(self, env):
        connect(env["client"])
        response = env["client"].get(
            "/coinbase/connection", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["connected"] is True
        assert body["key_reference"] == KEY_NAME
        assert "BEGIN" not in __import__("json").dumps(body)

    def test_diagnostics_are_redacted(self, env):
        connect(env["client"])
        response = env["client"].get(
            "/diagnostics", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 200
        text = __import__("json").dumps(response.json())
        assert "BEGIN" not in text
        assert env["database"].path.name in text
        assert response.json()["recent_events"] == []

    def test_coinbase_endpoints_require_the_session_token(self, env):
        client = env["client"]
        assert client.get("/coinbase/connection").status_code == 401
        assert client.post("/coinbase/disconnect").status_code == 401
        wrong = client.get(
            "/coinbase/connection", headers={"X-Local-Token": "nope"}
        )
        assert wrong.status_code == 401


class TestRetestAndDisconnect:
    def test_retest_uses_the_stored_secret(self, env):
        assert connect(env["client"]).status_code == 200
        env["stub"].cancel_status = 403
        response = env["client"].post(
            "/coinbase/test-connection", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 200
        assert response.json()["permissions"] == "view"

    def test_retest_updates_metadata_when_the_key_stops_working(self, env):
        connect(env["client"])
        env["stub"].accounts_status = 401
        response = env["client"].post(
            "/coinbase/test-connection", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 400
        assert response.json()["status"] == "invalid_credentials"
        status = env["client"].get(
            "/coinbase/connection", headers={"X-Local-Token": "s3cret"}
        ).json()
        assert status["connected"] is False

    def test_retest_without_a_connection_explains_how_to_proceed(self, env):
        response = env["client"].post(
            "/coinbase/test-connection", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 409
        body = response.json()
        assert body["status"] == "not_connected"
        assert "Paper and backtest modes work" in body["message"]

    def test_disconnect_removes_secret_and_reference(self, env):
        connect(env["client"])
        response = env["client"].post(
            "/coinbase/disconnect", headers={"X-Local-Token": "s3cret"}
        )
        assert response.status_code == 200
        assert response.json()["disconnected"] is True
        assert env["secrets"].get_secret(SECRET_KEY) is None
        status = env["client"].get(
            "/coinbase/connection", headers={"X-Local-Token": "s3cret"}
        ).json()
        assert status["connected"] is False
        assert status["key_reference"] is None

    def test_connecting_again_replaces_the_previous_credential(self, env):
        connect(env["client"])
        first_secret = env["secrets"].get_secret(SECRET_KEY)
        second = connect(env["client"])  # same provider, new key material
        assert second.status_code == 200
        assert env["secrets"].get_secret(SECRET_KEY) != first_secret
        status = env["client"].get(
            "/coinbase/connection", headers={"X-Local-Token": "s3cret"}
        ).json()
        assert status["connected"] is True
