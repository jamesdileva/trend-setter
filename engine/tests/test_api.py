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
