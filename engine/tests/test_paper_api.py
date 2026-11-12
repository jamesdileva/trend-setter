"""API tests for paper-trading endpoints (roadmap Sprint 9)."""

import pytest
from fastapi.testclient import TestClient

from trendbot.api.app import create_app
from trendbot.database import Database, upgrade_to_head
from trendbot.security.secret_store import InMemorySecretStore


@pytest.fixture()
def api_db(tmp_path):
    database = Database(tmp_path / "paper-api.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def api_secrets():
    return InMemorySecretStore()


def make_client(database: Database, secret_store) -> TestClient:
    app = create_app(local_token="s3cret", database=database, secret_store=secret_store)
    return TestClient(app, client=("127.0.0.1", 51000))


class TestPaperEndpoints:
    def test_start_creates_a_session_and_status_is_labeled(self, api_db, api_secrets):
        with make_client(api_db, api_secrets) as client:
            response = client.post("/paper/start", headers={"X-Local-Token": "s3cret"})
            assert response.status_code == 200
            assert response.json()["status"] == "running"

            status = client.get("/paper/status", headers={"X-Local-Token": "s3cret"}).json()
            assert status["account_kind"] == "paper"
            assert "PAPER TRADING" in status["warning"]
            assert status["cash"] == "1000"
            assert status["position"]["side"] == "flat"
            # Paper balances are never presented as exchange balances.
            assert "exchange" not in status["warning"].lower().replace("never", "")

    def test_controls_persist_across_requests(self, api_db, api_secrets):
        with make_client(api_db, api_secrets) as client:
            headers = {"X-Local-Token": "s3cret"}
            client.post("/paper/pause", headers=headers)
            status = client.get("/paper/status", headers=headers).json()
            assert status["mode"] == "entries_paused"
            assert status["entries_allowed"] is False

            client.post("/paper/emergency-stop", headers=headers)
            status = client.get("/paper/status", headers=headers).json()
            assert status["mode"] == "emergency_stopped"

            client.post("/paper/start", headers=headers)
            status = client.get("/paper/status", headers=headers).json()
            assert status["mode"] == "normal"

    def test_reset_requires_confirmation(self, api_db, api_secrets):
        with make_client(api_db, api_secrets) as client:
            headers = {"X-Local-Token": "s3cret"}
            client.post("/paper/start", headers=headers)
            refused = client.post("/paper/reset", headers=headers, json={"confirm": False})
            assert refused.status_code == 400
            assert refused.json()["status"] == "reset_not_confirmed"

            accepted = client.post("/paper/reset", headers=headers, json={"confirm": True})
            assert accepted.status_code == 200
            status = client.get("/paper/status", headers=headers).json()
            assert status["cash"] == "1000"

    def test_endpoints_require_the_session_token(self, api_db, api_secrets):
        with make_client(api_db, api_secrets) as client:
            for path in ("/paper/start", "/paper/pause", "/paper/stop", "/paper/reset"):
                assert client.post(path, json={}).status_code == 401
            assert client.get("/paper/status").status_code == 401
