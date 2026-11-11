"""Tests for the exchange adapter contract and the fake adapter.

The fake adapter encodes verified Coinbase semantics (see
docs/coinbase-verification-checklist.md): a duplicate client_order_id never
creates a second order, and products carry the current constraint field set.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trendbot.exchange.base import ExchangeAdapter
from trendbot.exchange.fake import FakeExchangeAdapter
from trendbot.exchange.types import OrderRequest, OrderSide
from trendbot.market_data.candles import Candle


@pytest.fixture()
def adapter() -> FakeExchangeAdapter:
    return FakeExchangeAdapter()


class TestAdapterContract:
    def test_fake_adapter_implements_the_full_contract(self):
        assert isinstance(FakeExchangeAdapter(), ExchangeAdapter)

    def test_unknown_product_error_is_plain_language(self, adapter: FakeExchangeAdapter):
        with pytest.raises(KeyError) as excinfo:
            adapter.get_product("SOL-USD")
        assert "not supported" in str(excinfo.value)
        assert "BTC-USD" in str(excinfo.value)

    def test_product_constraints_are_decimal_and_complete(self, adapter: FakeExchangeAdapter):
        product = adapter.get_product("BTC-USD")
        assert isinstance(product.base_increment, Decimal)
        assert isinstance(product.base_min_size, Decimal)
        assert product.product_id == "BTC-USD"
        assert product.trading_disabled is False

    def test_accounts_are_decimal_balances(self, adapter: FakeExchangeAdapter):
        accounts = {account.currency: account for account in adapter.get_accounts()}
        assert isinstance(accounts["USD"].available, Decimal)
        assert accounts["USD"].available > 0


class TestCandleGeneration:
    def test_history_is_deterministic_and_valid(self, adapter: FakeExchangeAdapter):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 1, 3, tzinfo=UTC)
        first = adapter.get_historical_candles("BTC-USD", "ONE_HOUR", start, end)
        second = adapter.get_historical_candles("BTC-USD", "ONE_HOUR", start, end)
        assert first == second
        assert len(first) == 3
        for candle in first:
            assert candle.validate() == []

    def test_unknown_product_raises_plain_language(self, adapter: FakeExchangeAdapter):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(KeyError):
            adapter.get_historical_candles("SOL-USD", "ONE_HOUR", start, start)


class TestOrderLifecycle:
    def _request(self, client_order_id: str = "c-1") -> OrderRequest:
        return OrderRequest(
            client_order_id=client_order_id,
            product_id="BTC-USD",
            side=OrderSide.BUY,
            base_size=Decimal("0.001"),
        )

    def test_order_is_accepted_with_exchange_id(self, adapter: FakeExchangeAdapter):
        result = adapter.create_order(self._request())
        assert result.accepted is True
        assert result.exchange_order_id is not None
        snapshot = adapter.get_order(result.exchange_order_id)
        assert snapshot is not None
        assert snapshot.status == "OPEN"

    def test_duplicate_client_order_id_never_creates_a_second_order(
        self, adapter: FakeExchangeAdapter
    ):
        first = adapter.create_order(self._request("c-1"))
        second = adapter.create_order(self._request("c-1"))
        assert first.accepted and second.accepted
        assert first.exchange_order_id == second.exchange_order_id
        assert len(adapter.list_open_orders()) == 1

    def test_unsupported_product_is_rejected_plain_language(self, adapter: FakeExchangeAdapter):
        request = OrderRequest(
            client_order_id="c-2", product_id="SOL-USD", side=OrderSide.BUY, base_size=Decimal("1")
        )
        result = adapter.create_order(request)
        assert result.accepted is False
        assert result.failure_reason is not None
        assert "not supported" in result.failure_reason

    def test_list_open_orders_filters_by_product(self, adapter: FakeExchangeAdapter):
        adapter.create_order(self._request("btc-1"))
        adapter.create_order(
            OrderRequest(
                client_order_id="eth-1",
                product_id="ETH-USD",
                side=OrderSide.SELL,
                base_size=Decimal("0.01"),
            )
        )
        assert len(adapter.list_open_orders("ETH-USD")) == 1
        assert adapter.list_open_orders("ETH-USD")[0].product_id == "ETH-USD"
        assert len(adapter.list_open_orders()) == 2

    def test_cancel_known_and_unknown_orders(self, adapter: FakeExchangeAdapter):
        result = adapter.create_order(self._request("c-1"))
        exchange_id = result.exchange_order_id
        assert exchange_id is not None
        assert adapter.cancel_order(exchange_id) is True
        assert adapter.list_open_orders() == []
        assert adapter.cancel_order("fake-does-not-exist") is False

    def test_fills_are_empty_until_fill_simulation_exists(self, adapter: FakeExchangeAdapter):
        adapter.create_order(self._request())
        assert adapter.list_fills() == []


class TestCandleModel:
    def test_invalid_candles_are_rejected_with_plain_language(self):
        bad_high = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("90"),
            close=Decimal("101"),
            volume=Decimal("1"),
        )
        problems = bad_high.validate()
        assert any("high" in problem for problem in problems)

    def test_negative_volume_is_rejected(self):
        candle = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("-1"),
        )
        assert any("volume" in problem for problem in candle.validate())
