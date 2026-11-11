"""API tests for the strategy endpoints (roadmap Sprint 6)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from trendbot.api.app import create_app
from trendbot.database import CandleRepository, Database, upgrade_to_head
from trendbot.market_data.candles import Candle
from trendbot.security.secret_store import InMemorySecretStore

START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture()
def api_db(tmp_path):
    database = Database(tmp_path / "strategy-api.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def api_secrets():
    return InMemorySecretStore()


def make_client(token: str | None = "s3cret", *, database: Database, secret_store) -> TestClient:
    app = create_app(local_token=token, database=database, secret_store=secret_store)
    return TestClient(app, client=("127.0.0.1", 51000))


def save_config(client: TestClient, **overrides) -> object:
    payload = {"product_id": "BTC-USD", "timeframe": "1h", "rsi_entry_ceiling": 97.0}
    payload.update(overrides)
    return client.post(
        "/strategy/config", headers={"X-Local-Token": "s3cret"}, json=payload
    )


def seed_jump_candles(db: Database) -> None:
    closes = [Decimal(60)] * 49 + [Decimal(55), Decimal(200)]
    CandleRepository(db).upsert_many(
        [
            Candle(
                product_id="BTC-USD",
                granularity="ONE_HOUR",
                start_time=START + index * timedelta(hours=1),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=Decimal(1),
            )
            for index, close in enumerate(closes)
        ]
    )


class TestConfigEndpoints:
    def test_save_and_read_back_the_active_config(self, api_db, api_secrets):
        with make_client(database=api_db, secret_store=api_secrets) as client:
            response = save_config(client)
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "saved"
            assert body["version"] == 1
            current = client.get("/strategy/current", headers={"X-Local-Token": "s3cret"}).json()
            assert current["configured"] is True
            assert current["config"]["fast_ema_period"] == 20
            assert current["config"]["config_hash"] == body["config_hash"]

    def test_invalid_config_is_rejected_with_plain_language(self, api_db, api_secrets):
        with make_client(database=api_db, secret_store=api_secrets) as client:
            response = save_config(client, fast_ema_period=50, slow_ema_period=20)
            assert response.status_code == 400
            body = response.json()
            assert body["status"] == "invalid_config"
            assert "fast EMA period" in body["message"]

    def test_endpoints_require_the_session_token(self, api_db, api_secrets):
        with make_client(database=api_db, secret_store=api_secrets) as client:
            assert client.post("/strategy/config", json={}).status_code == 401
            assert client.get("/strategy/current").status_code == 401
            assert client.post("/strategy/evaluate", json={}).status_code == 401


class TestEvaluateEndpoint:
    def test_evaluate_without_config_is_conflict(self, api_db, api_secrets):
        with make_client(database=api_db, secret_store=api_secrets) as client:
            response = client.post(
                "/strategy/evaluate", headers={"X-Local-Token": "s3cret"}, json={}
            )
            assert response.status_code == 409
            assert response.json()["status"] == "not_configured"

    def test_evaluate_with_no_stored_candles_holds_with_reason(self, api_db, api_secrets):
        with make_client(database=api_db, secret_store=api_secrets) as client:
            save_config(client)
            response = client.post(
                "/strategy/evaluate", headers={"X-Local-Token": "s3cret"}, json={}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["signal"] == "hold"
            assert body["reason_code"] == "no_data"

    def test_evaluate_returns_and_persists_the_decision(self, api_db, api_secrets):
        with make_client(database=api_db, secret_store=api_secrets) as client:
            save_config(client)
            seed_jump_candles(api_db)
            response = client.post(
                "/strategy/evaluate", headers={"X-Local-Token": "s3cret"}, json={}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["signal"] == "buy"
            assert body["reason_code"] == "bullish_crossover_rsi_ok"
            expected_time = (START + timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
            assert body["candle_time"] == expected_time

            # Repeated evaluation of the same candle: same decision, one signal row.
            repeat = client.post(
                "/strategy/evaluate", headers={"X-Local-Token": "s3cret"}, json={}
            )
            assert repeat.json() == body
            current = client.get("/strategy/current", headers={"X-Local-Token": "s3cret"}).json()
            assert len(current["recent_signals"]) == 1
