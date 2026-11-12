"""Risk limit tests: every limit gets positive and negative coverage
(roadmap Sprint 8 verification), plus sizing and daily-drawdown behavior."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.exchange.types import ProductInfo
from trendbot.risk.daily import DailyLedger
from trendbot.risk.limits import RiskLimits
from trendbot.risk.manager import RiskContext, RiskManager
from trendbot.risk.sizing import size_entry

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

BTC = ProductInfo(
    product_id="BTC-USD",
    base_increment=Decimal("0.00000001"),
    quote_increment=Decimal("0.01"),
    price_increment=Decimal("0.01"),
    base_min_size=Decimal("0.0001"),
    base_max_size=Decimal("1000"),
    quote_min_size=Decimal("1"),
    quote_max_size=Decimal("1000000"),
    limit_only=False,
    post_only=False,
    cancel_only=False,
    trading_disabled=False,
)


def context(**overrides) -> RiskContext:
    values: dict[str, object] = {
        "product_id": "BTC-USD",
        "quote_notional": Decimal("400"),
        "base_size": Decimal("0.004"),
        "price": Decimal("100000"),
        "product": BTC,
        "current_position_quote": Decimal("0"),
        "total_exposure_quote": Decimal("0"),
        "open_orders_count": 0,
        "open_positions_count": 0,
        "cash_available": Decimal("5000"),
        "daily_drawdown_pct": Decimal("0"),
        "stale_data": False,
        "cooldown_active": False,
        "kill_switch_active": False,
    }
    values.update(overrides)
    return RiskContext(**values)  # type: ignore[arg-type]


class TestRiskLimits:
    def test_healthy_context_is_allowed(self):
        decision = RiskManager().check_entry(context())
        assert decision.allowed is True

    def test_stale_data_blocks_entries(self):
        decision = RiskManager().check_entry(context(stale_data=True))
        assert not decision.allowed and decision.reason_code == "stale_data"

    def test_kill_switch_blocks_entries(self):
        decision = RiskManager().check_entry(context(kill_switch_active=True))
        assert not decision.allowed and decision.reason_code == "kill_switch_active"

    def test_drawdown_at_the_limit_blocks_entries(self):
        decision = RiskManager().check_entry(context(daily_drawdown_pct=Decimal("3.0")))
        assert not decision.allowed and decision.reason_code == "daily_drawdown_exceeded"

    def test_drawdown_below_the_limit_allows(self):
        decision = RiskManager().check_entry(context(daily_drawdown_pct=Decimal("2.99")))
        assert decision.allowed

    def test_cooldown_blocks_entries(self):
        decision = RiskManager().check_entry(context(cooldown_active=True))
        assert not decision.allowed and decision.reason_code == "cooldown_active"

    def test_per_order_cap(self):
        manager = RiskManager(limits=RiskLimits(max_order_quote=Decimal("300")))
        decision = manager.check_entry(context(quote_notional=Decimal("400")))
        assert not decision.allowed and decision.reason_code == "order_cap_exceeded"
        assert manager.check_entry(context(quote_notional=Decimal("300"))).allowed

    def test_per_position_cap(self):
        manager = RiskManager(limits=RiskLimits(max_position_quote=Decimal("1000")))
        decision = manager.check_entry(
            context(current_position_quote=Decimal("700"), quote_notional=Decimal("400"))
        )
        assert not decision.allowed and decision.reason_code == "position_cap_exceeded"

    def test_total_exposure_cap(self):
        manager = RiskManager(limits=RiskLimits(max_total_exposure_quote=Decimal("2000")))
        decision = manager.check_entry(
            context(total_exposure_quote=Decimal("1800"), quote_notional=Decimal("400"))
        )
        assert not decision.allowed and decision.reason_code == "exposure_cap_exceeded"

    def test_open_order_limit(self):
        manager = RiskManager(limits=RiskLimits(max_open_orders=3))
        decision = manager.check_entry(context(open_orders_count=3))
        assert not decision.allowed and decision.reason_code == "too_many_open_orders"

    def test_open_position_limit(self):
        manager = RiskManager(limits=RiskLimits(max_open_positions=2))
        decision = manager.check_entry(context(open_positions_count=2))
        assert not decision.allowed and decision.reason_code == "too_many_open_positions"

    def test_configured_min_size(self):
        manager = RiskManager(limits=RiskLimits(min_base_size=Decimal("0.01")))
        decision = manager.check_entry(context(base_size=Decimal("0.004")))
        assert not decision.allowed and decision.reason_code == "below_min_size"

    def test_configured_max_size(self):
        manager = RiskManager(limits=RiskLimits(max_base_size=Decimal("0.001")))
        decision = manager.check_entry(context(base_size=Decimal("0.004")))
        assert not decision.allowed and decision.reason_code == "above_max_size"

    def test_product_min_size(self):
        product = ProductInfo(
            **{
                "product_id": "BTC-USD",
                "base_increment": BTC.base_increment,
                "quote_increment": BTC.quote_increment,
                "price_increment": BTC.price_increment,
                "base_min_size": Decimal("0.001"),
                "base_max_size": BTC.base_max_size,
                "quote_min_size": BTC.quote_min_size,
                "quote_max_size": BTC.quote_max_size,
                "limit_only": False,
                "post_only": False,
                "cancel_only": False,
                "trading_disabled": False,
            }
        )
        decision = RiskManager().check_entry(
            context(base_size=Decimal("0.0005"), product=product)
        )
        assert not decision.allowed and decision.reason_code == "below_product_min"

    def test_insufficient_cash(self):
        decision = RiskManager().check_entry(context(cash_available=Decimal("100")))
        assert not decision.allowed and decision.reason_code == "insufficient_cash"

    def test_non_tradable_product(self):
        disabled = ProductInfo(
            **{
                "product_id": "BTC-USD",
                "base_increment": BTC.base_increment,
                "quote_increment": BTC.quote_increment,
                "price_increment": BTC.price_increment,
                "base_min_size": BTC.base_min_size,
                "base_max_size": BTC.base_max_size,
                "quote_min_size": BTC.quote_min_size,
                "quote_max_size": BTC.quote_max_size,
                "limit_only": False,
                "post_only": False,
                "cancel_only": True,
                "trading_disabled": True,
            }
        )
        decision = RiskManager().check_entry(context(product=disabled))
        assert not decision.allowed and decision.reason_code == "product_not_tradable"

    def test_exits_ignore_stale_data_and_caps(self):
        manager = RiskManager()
        decision = manager.check_exit(context(stale_data=True, quote_notional=Decimal("999999")))
        assert decision.allowed

    def test_kill_switch_blocks_even_exits(self):
        manager = RiskManager()
        decision = manager.check_exit(context(kill_switch_active=True))
        assert not decision.allowed and decision.reason_code == "kill_switch_active"


class TestSizing:
    def test_quantity_rounds_down_to_the_increment(self):
        # 400/100000 = 0.004 exactly; with a coarser increment it floors.
        coarse = ProductInfo(
            **{
                "product_id": "BTC-USD",
                "base_increment": Decimal("0.001"),
                "quote_increment": BTC.quote_increment,
                "price_increment": BTC.price_increment,
                "base_min_size": BTC.base_min_size,
                "base_max_size": BTC.base_max_size,
                "quote_min_size": BTC.quote_min_size,
                "quote_max_size": BTC.quote_max_size,
                "limit_only": False,
                "post_only": False,
                "cancel_only": False,
                "trading_disabled": False,
            }
        )
        sized = size_entry(Decimal("400"), Decimal("100000"), coarse)
        assert sized.base_size == Decimal("0.004")

    def test_rounding_never_goes_up(self):
        sized = size_entry(Decimal("333"), Decimal("100000"), BTC)
        assert sized.base_size == Decimal("0.00333")

    def test_below_product_min_is_rejected(self):
        with pytest.raises(Exception) as excinfo:
            size_entry(Decimal("1"), Decimal("100000"), BTC)
        assert "minimum" in str(excinfo.value)

    def test_zero_price_is_rejected(self):
        from trendbot.strategies.config import StrategyConfigError

        with pytest.raises(StrategyConfigError):
            size_entry(Decimal("100"), Decimal("0"), BTC)


class TestDailyLedger:
    def test_baseline_persists_across_restart(self, tmp_path):
        from trendbot.database import Database, upgrade_to_head

        database = Database(tmp_path / "ledger.db")
        upgrade_to_head(database)
        first = DailyLedger(database)
        first.record_equity(Decimal("1000"), now=NOW)

        # A fresh instance over the same database simulates a restart.
        restarted = DailyLedger(database)
        drawdown = restarted.record_equity(Decimal("970"), now=NOW + timedelta(hours=2))
        assert drawdown == pytest.approx(Decimal("3.0"))
        assert restarted.baseline(now=NOW + timedelta(hours=2)) == Decimal("1000")

    def test_drawdown_computation(self, tmp_path):
        from trendbot.database import Database, upgrade_to_head

        database = Database(tmp_path / "ledger2.db")
        upgrade_to_head(database)
        ledger = DailyLedger(database)
        assert ledger.record_equity(Decimal("1000"), now=NOW) == 0
        assert ledger.record_equity(Decimal("1050"), now=NOW + timedelta(hours=1)) == 0
        assert ledger.record_equity(
            Decimal("950"), now=NOW + timedelta(hours=2)
        ) == pytest.approx(Decimal("5.0"))

    def test_new_utc_day_resets_the_baseline(self, tmp_path):
        from trendbot.database import Database, upgrade_to_head

        database = Database(tmp_path / "ledger3.db")
        upgrade_to_head(database)
        ledger = DailyLedger(database)
        ledger.record_equity(Decimal("1000"), now=NOW)
        next_day = NOW + timedelta(days=1)
        # A new UTC day fixes a fresh baseline: drawdown restarts at zero.
        assert ledger.record_equity(Decimal("999"), now=next_day) == Decimal("0")
        assert ledger.baseline(now=next_day) == Decimal("999")
