"""Offline tests for the live Coinbase execution adapter (Sprint 10).

All HTTP interactions run through ``httpx.MockTransport`` — no network,
no real keys, no real orders. The adapter's behavior is pinned to the
Sprint 0 verification (order configurations, status mapping, client
order id semantics, fills identity).
"""

from decimal import Decimal

import httpx
import pytest

from trendbot.exchange.coinbase_live import CoinbaseLiveExecutionAdapter
from trendbot.exchange.types import OrderRequest, OrderSide

KEY_NAME = "organizations/test-org/apiKeys/test-key"


def make_adapter(handler) -> CoinbaseLiveExecutionAdapter:
    return CoinbaseLiveExecutionAdapter(
        key_name=KEY_NAME,
        private_key_pem=_pem(),
        transport=httpx.MockTransport(handler),
    )


def _pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def product_payload() -> dict[str, str]:
    return {
        "product_id": "BTC-USD",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.0001",
        "base_max_size": "1000",
        "quote_min_size": "1",
        "quote_max_size": "1000000",
        "limit_only": "false",
        "post_only": "false",
        "cancel_only": "false",
        "trading_disabled": "false",
    }


def order_payload(status: str = "OPEN", order_id: str = "live-001") -> dict[str, str]:
    return {
        "order_id": order_id,
        "client_order_id": "test-cid",
        "product_id": "BTC-USD",
        "side": "BUY",
        "status": status,
        "filled_size": "0",
        "total_fees": "0",
        "created_time": "2026-01-01T12:00:00Z",
    }


def limit_order_request(cid: str = "test-cid") -> OrderRequest:
    return OrderRequest(
        client_order_id=cid,
        product_id="BTC-USD",
        side=OrderSide.BUY,
        base_size=Decimal("0.004"),
        limit_price=Decimal("100000"),
    )


class TestPlaceOrder:
    def test_limit_gtc_configuration_is_sent(self):
        captured: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json_body(request))
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "success_response": {"order_id": "live-001", "client_order_id": "test-cid"},
                },
            )

        adapter = make_adapter(handler)
        result = adapter.create_order(limit_order_request())
        assert result.accepted is True
        assert result.exchange_order_id == "live-001"
        body = captured[0]
        config = body["order_configuration"]
        assert "limit_limit_gtc" in config
        assert config["limit_limit_gtc"]["limit_price"] == "100000"

    def test_market_configuration_for_market_orders(self):
        captured: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json_body(request))
            return httpx.Response(
                200,
                json={"success": True, "success_response": {"order_id": "live-002"}},
            )

        adapter = make_adapter(handler)
        request = OrderRequest(
            client_order_id="mkt-1",
            product_id="BTC-USD",
            side=OrderSide.BUY,
            base_size=Decimal("0.004"),
        )
        result = adapter.create_order(request)
        assert result.accepted is True
        assert "market_market_ioc" in captured[0]["order_configuration"]

    def test_client_order_id_travels_on_every_order(self):
        captured: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json_body(request))
            return httpx.Response(
                200, json={"success": True, "success_response": {"order_id": "x"}}
            )

        adapter = make_adapter(handler)
        adapter.create_order(limit_order_request("unique-cid-42"))
        assert captured[0]["client_order_id"] == "unique-cid-42"

    def test_exchange_rejection_returns_failure_reason(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "error_response": {
                        "failure_reason": "INSUFFICIENT_FUND",
                        "message": "Insufficient funds",
                    },
                },
            )

        adapter = make_adapter(handler)
        result = adapter.create_order(limit_order_request())
        assert result.accepted is False
        assert result.failure_reason == "INSUFFICIENT_FUND"

    def test_network_failure_raises_unknown_outcome(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection reset")

        adapter = make_adapter(handler)
        from trendbot.exchange.base import UnknownOutcomeError

        with pytest.raises(UnknownOutcomeError) as excinfo:
            adapter.create_order(limit_order_request())
        assert excinfo.value.client_order_id == "test-cid"


class TestOrderStatus:
    def test_status_mapping_to_internal_vocabulary(self):
        cases = {
            "OPEN": "OPEN",
            "FILLED": "FILLED",
            "CANCELLED": "CANCELED",
            "EXPIRED": "CANCELED",
            "FAILED": "REJECTED",
            "PENDING": "OPEN",
            "QUEUED": "OPEN",
        }
        for coinbase_status, expected in cases.items():
            def handler(_r: httpx.Request, s: str = coinbase_status) -> httpx.Response:
                return httpx.Response(200, json={"order": order_payload(status=s, order_id="oid")})

            adapter = make_adapter(handler)
            snapshot = adapter.get_order("oid")
            assert snapshot is not None
            assert snapshot.status == expected, f"{coinbase_status} → {expected}"

    def test_get_order_returns_none_for_missing(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        adapter = make_adapter(handler)
        assert adapter.get_order("missing") is None


class TestCancel:
    def test_cancel_success(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"results": [{"order_id": "live-001", "success": True}]}
            )

        adapter = make_adapter(handler)
        assert adapter.cancel_order("live-001") is True

    def test_cancel_failure(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "order_id": "live-001",
                            "success": False,
                            "failure_reason": "ORDER_IS_FULLY_FILLED",
                        }
                    ]
                },
            )

        adapter = make_adapter(handler)
        assert adapter.cancel_order("live-001") is False


class TestFills:
    def test_fills_parse_with_pagination(self):
        page1 = {
            "fills": [
                {
                    "entry_id": "e-1",
                    "trade_id": "t-1",
                    "order_id": "live-001",
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "price": "100000",
                    "size": "0.002",
                    "commission": "2",
                    "trade_time": "2026-01-01T12:00:00Z",
                }
            ],
            "cursor": "next-page",
        }
        page2 = {
            "fills": [
                {
                    "entry_id": "e-2",
                    "trade_id": "t-2",
                    "order_id": "live-001",
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "price": "100000",
                    "size": "0.002",
                    "commission": "2",
                    "trade_time": "2026-01-01T12:05:00Z",
                }
            ],
            "cursor": "",
        }
        pages = [page1, page2]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=pages.pop(0))

        adapter = make_adapter(handler)
        fills = adapter.list_fills("BTC-USD")
        assert len(fills) == 2
        assert fills[0].trade_id == "t-1"
        assert fills[0].side == OrderSide.BUY
        assert fills[1].trade_id == "t-2"


class TestAccountsAndProducts:
    def test_accounts_parse(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "accounts": [
                        {"uuid": "u", "currency": "USD", "available": "5000.00", "hold": "10.00"}
                    ]
                },
            )

        adapter = make_adapter(handler)
        accounts = adapter.get_accounts()
        assert accounts[0].available == Decimal("5000.00")

    def test_product_parses_decimal_constraints(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=product_payload())

        adapter = make_adapter(handler)
        product = adapter.get_product("BTC-USD")
        assert product.base_increment == Decimal("0.00000001")
        assert product.base_min_size == Decimal("0.0001")


class TestPermissionFailures:
    def test_401_raises_invalid_credentials(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        adapter = make_adapter(handler)
        from trendbot.exchange.coinbase_rest import InvalidCredentialsError

        with pytest.raises(InvalidCredentialsError):
            adapter.test_connection()

    def test_403_raises_insufficient_permissions(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "forbidden"})

        adapter = make_adapter(handler)
        from trendbot.exchange.coinbase_rest import InsufficientPermissionsError

        with pytest.raises(InsufficientPermissionsError):
            adapter.test_connection()


class TestNoWithdrawalPaths:
    def test_adapter_source_has_no_withdrawal_or_transfer_endpoints(self):
        """The adapter must never reference withdrawal/transfer/move-funds APIs."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "src" / "trendbot" / "exchange" / "coinbase_live.py"
        )
        text = source.read_text(encoding="utf-8")
        for forbidden in (
            "move_funds",
            "withdraw",
            "withdrawal",
            "intx/allocate",
            "convert",
        ):
            assert forbidden not in text.lower(), f"forbidden endpoint reference: {forbidden}"


def json_body(request: httpx.Request) -> dict[str, object]:
    import json as json_module

    return json_module.loads(request.content.decode())
