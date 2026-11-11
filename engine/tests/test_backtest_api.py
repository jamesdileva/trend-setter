"""API tests for the labeled historical-simulation endpoints (Sprint 7)."""

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
    database = Database(tmp_path / "backtest-api.db")
    upgrade_to_head(database)
    return database


@pytest.fixture()
def api_secrets():
    return InMemorySecretStore()


def make_client(database: Database, secret_store) -> TestClient:
    app = create_app(local_token="s3cret", database=database, secret_store=secret_store)
    return TestClient(app, client=("127.0.0.1", 51000))


def seed_candles(db: Database, count: int = 61) -> None:
    """Flat 60s, one dip, one jump — guarantees an evaluable crossover.

    49 candles at 60, candle 50 at 55, candle 51 at 200, then continued
    rises. With an entry ceiling of 97 (RSI computes to ≈96.9 at the jump)
    the baseline strategy produces a BUY that the simulation fills.
    """
    closes = [Decimal(60)] * 49 + [Decimal(55), Decimal(200)] + [
        Decimal(200 + index) for index in range(max(count - 51, 0))
    ]
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


def run_request(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "product_id": "BTC-USD",
        "timeframe": "1h",
        "start": "2025-12-31",
        "end": "2026-02-01",
        "rsi_entry_ceiling": 97.0,
    }
    payload.update(overrides)
    return payload


class TestBacktestEndpoint:
    def test_run_is_labeled_and_persisted(self, api_db, api_secrets):
        seed_candles(api_db, count=60)
        with make_client(api_db, api_secrets) as client:
            response = client.post(
                "/backtest/run", headers={"X-Local-Token": "s3cret"}, json=run_request()
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "simulation_complete"
            assert "HISTORICAL SIMULATION" in body["warning"]
            assert body["result"]["trade_count"] >= 1
            assert len(body["result"]["trades"]) == body["result"]["trade_count"]
            assert body["out_of_sample"]["out_of_sample"]["candles"] > 0

            listed = client.get(
                "/backtest/runs", headers={"X-Local-Token": "s3cret"}
            ).json()
            assert listed["runs"][0]["run_id"] == body["run_id"]
            assert "HISTORICAL SIMULATIONS" in listed["warning"]

    def test_insufficient_stored_candles_is_a_conflict_with_guidance(self, api_db, api_secrets):
        seed_candles(api_db, count=5)
        with make_client(api_db, api_secrets) as client:
            response = client.post(
                "/backtest/run", headers={"X-Local-Token": "s3cret"}, json=run_request()
            )
            assert response.status_code == 409
            body = response.json()
            assert body["status"] == "insufficient_data"
            assert "Import more history" in body["message"]

    def test_invalid_timeframe_is_rejected_plain_language(self, api_db, api_secrets):
        seed_candles(api_db, count=60)
        with make_client(api_db, api_secrets) as client:
            response = client.post(
                "/backtest/run",
                headers={"X-Local-Token": "s3cret"},
                json=run_request(timeframe="3h"),
            )
            assert response.status_code == 400
            assert "not supported" in response.json()["message"]

    def test_endpoints_require_the_session_token(self, api_db, api_secrets):
        with make_client(api_db, api_secrets) as client:
            assert client.post("/backtest/run", json=run_request()).status_code == 401
            assert client.get("/backtest/runs").status_code == 401

    def test_repeated_runs_persist_separately_and_deterministically(self, api_db, api_secrets):
        seed_candles(api_db, count=60)
        with make_client(api_db, api_secrets) as client:
            first = client.post(
                "/backtest/run", headers={"X-Local-Token": "s3cret"}, json=run_request()
            ).json()
            second = client.post(
                "/backtest/run", headers={"X-Local-Token": "s3cret"}, json=run_request()
            ).json()
            assert first["result"] == second["result"]
            assert first["run_id"] != second["run_id"]
            listed = client.get("/backtest/runs", headers={"X-Local-Token": "s3cret"}).json()
            assert len(listed["runs"]) == 2
