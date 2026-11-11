"""Candle data source selection: authenticated when connected, public otherwise.

Shared by the operator CLI (Sprint 4) and the gap backfiller (Sprint 5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from trendbot.application.coinbase_connection import (
    SECRET_KEY,
    CoinbaseConnectionService,
    default_client_factory,
)
from trendbot.database.session import Database
from trendbot.exchange.coinbase_rest import CoinbaseRestClient, fetch_public_candles
from trendbot.market_data.granularity import granularity_for_timeframe
from trendbot.market_data.importer import CandlePageLike

FetchPage = Callable[[datetime, datetime], CandlePageLike]


def build_fetch_page(
    database: Database, product_id: str, timeframe: str, *, quiet: bool = True
) -> FetchPage:
    """Build the fetch callable: authenticated if a credential is connected.

    Public (unauthenticated) endpoints need no API key and cover
    paper/backtest use; authenticated requests are used when the user has
    connected a key (secret read from the OS store at call time).
    """
    secrets = None

    def public_fetch(w_start: datetime, w_end: datetime) -> CandlePageLike:
        granularity = granularity_for_timeframe(timeframe)
        return fetch_public_candles(product_id, granularity, w_start, w_end)

    def authenticated_fetch(key_name: str, private_key_pem: str) -> FetchPage:
        client = CoinbaseRestClient(key_name=key_name, private_key_pem=private_key_pem)
        granularity = granularity_for_timeframe(timeframe)

        def fetch(w_start: datetime, w_end: datetime) -> CandlePageLike:
            return client.get_candles(product_id, granularity, w_start, w_end)

        return fetch

    # Lazy import avoids a security <-> market_data cycle at module load.
    from trendbot.security.secret_store import default_secret_store

    secrets = default_secret_store()
    service = CoinbaseConnectionService(database, secrets, default_client_factory())
    state = service.status()
    if not state.connected:
        if not quiet:
            print("No connected Coinbase credential — using public data endpoints.")
        return public_fetch
    key_name = state.key_reference
    private_key = secrets.get_secret(SECRET_KEY)
    if key_name is None or private_key is None:
        if not quiet:
            print(
                "Credential reference found but secret unavailable — "
                "falling back to public endpoints."
            )
        return public_fetch
    return authenticated_fetch(key_name, private_key)
