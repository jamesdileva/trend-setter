"""Tests for the loopback local API boundary (architecture.md §15).

Note: the loopback middleware rejects any client that is not 127.0.0.1/::1,
so every client here explicitly passes a loopback (or explicitly remote)
address — the TestClient default of ``testclient`` must never be used.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from trendbot import __version__
from trendbot.api.app import create_app
from trendbot.application.state import EngineState
from trendbot.database import Database, upgrade_to_head
from trendbot.security.secret_store import InMemorySecretStore


@pytest.fixture()
def api_database(tmp_path):
    database = Database(tmp_path / "api.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def api_secrets():
    return InMemorySecretStore()


def make_client(
    token: str | None = None,
    client_host: str = "127.0.0.1",
    *,
    database: Database,
    secret_store: InMemorySecretStore,
) -> TestClient:
    app = create_app(local_token=token, database=database, secret_store=secret_store)
    return TestClient(app, client=(client_host, 51000))


class TestHealth:
    def test_health_is_available_without_a_token(self, api_database, api_secrets):
        with make_client(database=api_database, secret_store=api_secrets) as client:
            response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["engine_version"] == __version__
        assert body["utc_time"].endswith("Z")

    def test_openapi_docs_are_disabled(self, api_database, api_secrets):
        with make_client(database=api_database, secret_store=api_secrets) as client:
            assert client.get("/openapi.json").status_code == 404
            assert client.get("/docs").status_code == 404


class TestLoopbackBoundary:
    @pytest.mark.parametrize("remote_host", ["192.0.2.10", "10.1.2.3", "172.16.0.9"])
    def test_non_loopback_clients_are_rejected(
        self, remote_host, api_database, api_secrets
    ):
        with make_client(
            client_host=remote_host, database=api_database, secret_store=api_secrets
        ) as client:
            response = client.get("/health")
        assert response.status_code == 403
        assert "only available on this computer" in response.json()["detail"]

    def test_loopback_ipv6_is_accepted(self, api_database, api_secrets):
        with make_client(
            client_host="::1", database=api_database, secret_store=api_secrets
        ) as client:
            assert client.get("/health").status_code == 200


class TestStatusEndpoint:
    def test_status_requires_the_session_token(self, api_database, api_secrets):
        with make_client(
            token="s3cret", database=api_database, secret_store=api_secrets
        ) as client:
            missing = client.get("/status")
            wrong = client.get("/status", headers={"X-Local-Token": "wrong"})
        assert missing.status_code == 401
        assert wrong.status_code == 401

    def test_status_with_valid_token_reports_paper_state(
        self, api_database, api_secrets
    ):
        started = datetime.now(UTC)
        with make_client(
            token="s3cret", database=api_database, secret_store=api_secrets
        ) as client:
            response = client.get("/status", headers={"X-Local-Token": "s3cret"})
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "paper"
        assert body["state"] == EngineState.RUNNING_PAPER.value
        assert body["engine_version"] == __version__
        assert body["started_at"].startswith(f"{started:%Y-%m-%dT%H}")

    def test_startup_without_a_token_leaves_status_unavailable(
        self, api_database, api_secrets
    ):
        with make_client(
            token=None, database=api_database, secret_store=api_secrets
        ) as client:
            response = client.get("/status", headers={"X-Local-Token": "anything"})
        assert response.status_code == 503
        assert "without a session token" in response.json()["detail"]

    def test_there_is_no_order_endpoint(self, api_database, api_secrets):
        with make_client(
            token="s3cret", database=api_database, secret_store=api_secrets
        ) as client:
            for path in ("/orders", "/engine/order", "/trading/order"):
                response = client.post(
                    path,
                    headers={"X-Local-Token": "s3cret"},
                    json={"product_id": "BTC-USD", "side": "buy"},
                )
            assert response.status_code == 404


class TestNotificationsEndpoints:
    """Email notification settings: token-gated, password write-only (Sprint 15)."""

    def make_notifier_client(self, api_database, api_secrets):
        from trendbot.notifications import NotificationService

        notifier = NotificationService(api_database, api_secrets)
        app = create_app(
            local_token="s3cret",
            database=api_database,
            secret_store=api_secrets,
            notifier=notifier,
        )
        return TestClient(app, client=("127.0.0.1", 51000))

    def test_endpoints_require_the_session_token(self, api_database, api_secrets):
        with self.make_notifier_client(api_database, api_secrets) as client:
            assert client.get("/notifications/email").status_code == 401
            assert client.post(
                "/notifications/email", json={"enabled": False}
            ).status_code == 401
            assert client.post("/notifications/email/test").status_code == 401

    def test_save_roundtrip_never_returns_the_password(self, api_database, api_secrets):
        with self.make_notifier_client(api_database, api_secrets) as client:
            headers = {"X-Local-Token": "s3cret"}
            payload = {
                "enabled": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "security": "ssl",
                "username": "alerter@example.com",
                "recipient": "me@example.com",
                "password": "app-password-9",
            }
            saved = client.post("/notifications/email", json=payload, headers=headers)
            assert saved.status_code == 200
            status = client.get("/notifications/email", headers=headers).json()
            assert status["available"] is True
            assert status["enabled"] is True
            assert status["smtp_host"] == "smtp.example.com"
            assert status["has_password"] is True
            body = str(status)
            assert "app-password-9" not in body

    def test_invalid_recipient_is_rejected_in_plain_language(self, api_database, api_secrets):
        with self.make_notifier_client(api_database, api_secrets) as client:
            response = client.post(
                "/notifications/email",
                json={"enabled": True, "smtp_host": "smtp.example.com",
                      "recipient": "nope", "password": "x"},
                headers={"X-Local-Token": "s3cret"},
            )
            assert response.status_code == 400
            assert "email address" in response.json()["message"]

    def test_unwired_notifier_reports_unavailable(self, api_database, api_secrets):
        with make_client(
            token="s3cret", database=api_database, secret_store=api_secrets
        ) as client:
            headers = {"X-Local-Token": "s3cret"}
            assert client.get("/notifications/email", headers=headers).json() == {
                "available": False
            }
            assert client.post(
                "/notifications/email/test", headers=headers
            ).status_code == 503
