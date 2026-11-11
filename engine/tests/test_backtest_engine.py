"""Hand-calculated backtest scenarios (roadmap Sprint 7 verification).

Candles are exact-by-construction; a scripted strategy decides at chosen
indices so every fill, fee, and PnL number is hand-checkable. Fees and
slippage are the conservative placeholder assumptions, never exchange facts.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.backtesting.assumptions import FeeAssumptions
from trendbot.backtesting.engine import END_OF_DATA, BacktestEngine
from trendbot.market_data.candles import Candle
from trendbot.strategies.base import Strategy
from trendbot.strategies.config import EmaRsiConfig
from trendbot.strategies.decisions import SignalType, StrategyDecision, StrategyPosition

START = datetime(2026, 1, 1, tzinfo=UTC)
HOURLY = timedelta(hours=1)


def candles_from(opens_closes: list[tuple[int, int]]) -> list[Candle]:
    out = []
    for index, (open_, close) in enumerate(opens_closes):
        out.append(
            Candle(
                product_id="BTC-USD",
                granularity="ONE_HOUR",
                start_time=START + index * HOURLY,
                open=Decimal(open_),
                high=Decimal(max(open_, close)) + 1,
                low=Decimal(min(open_, close)) - 1,
                close=Decimal(close),
                volume=Decimal(1),
            )
        )
    return out


class ScriptedStrategy(Strategy):
    """Decides at chosen candle indices — full control for hand math."""

    name = "scripted"
    version = "0.0.1"

    def __init__(self, actions: dict[int, str], *, record: list | None = None) -> None:
        self._actions = actions
        self._record = record

    def validate_config(self, config: object) -> None:
        return None

    def required_history(self, config: object) -> int:
        return 1

    def evaluate(
        self,
        candles: list[Candle],
        config: object,
        position: StrategyPosition | None = None,
    ) -> StrategyDecision:
        index = len(candles) - 1
        signal = SignalType(self._actions.get(index, "hold"))
        if self._record is not None:
            self._record.append((index, signal))
        return StrategyDecision(
            product_id=candles[-1].product_id,
            timeframe="1h",
            candle_time=candles[-1].start_time,
            signal=signal,
            reason_code="scripted",
            explanation="",
            indicator_values={},
            strategy_name=self.name,
            strategy_version=self.version,
            config_hash="scripted",
        )


def engine(
    *,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    initial_quote: Decimal = Decimal("1000"),
    position_size_quote: Decimal = Decimal("500"),
) -> BacktestEngine:
    return BacktestEngine(
        strategy=ScriptedStrategy({}),
        assumptions=FeeAssumptions(
            fee_bps=fee_bps, slippage_bps=slippage_bps
        ),
        initial_quote=initial_quote,
        position_size_quote=position_size_quote,
    )


def run_with(
    actions: dict[int, str],
    opens_closes: list[tuple[int, int]],
    *,
    record: list | None = None,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> object:
    config = EmaRsiConfig(product_id="BTC-USD", timeframe="1h")
    scripted = ScriptedStrategy(actions, record=record)
    runner = engine(fee_bps=fee_bps, slippage_bps=slippage_bps)
    runner.strategy = scripted
    return runner.run(candles_from(opens_closes), config)


class TestHandScenarios:
    def test_losing_trade_with_fees_matches_hand_math(self):
        # BUY decided at c0 (fills c1 open 110), SELL at c1 (fills c2 open 90).
        # notional 500, fee 1% per side, slippage 0.
        # base = floor(500/110, 1e-8) = 4.54545454
        # proceeds = 409.0909086; fee_exit = 4.090909086
        # pnl = 409.0909086 - 4.090909086 - 505 = -100.0000005
        result = run_with(
            {0: "buy", 1: "sell"},
            [(100, 100), (110, 110), (90, 90), (100, 100)],
            fee_bps=100.0,
        )
        assert result.metrics.trade_count == 1
        trade = result.trades[0]
        assert trade.entry_price == Decimal("110")
        assert trade.exit_price == Decimal("90")
        assert trade.base_size == Decimal("4.54545454")
        assert trade.fee_entry == Decimal("5.0000")
        assert trade.pnl_quote == pytest.approx(Decimal("-100"), abs=Decimal("0.001"))
        fees = pytest.approx(Decimal("9.0909"), abs=Decimal("0.001"))
        assert result.metrics.total_fees_quote == fees
        assert result.metrics.net_return_pct == pytest.approx(Decimal("-10"), abs=Decimal("0.001"))
        # Fees make the net worse than the gross price move alone.
        assert result.metrics.net_return_pct < result.metrics.gross_return_pct
        assert result.metrics.max_drawdown_pct == pytest.approx(Decimal("10"), abs=Decimal("0.01"))
        # The position was sold at candle 2's open, so only candle 1 is in-market.
        assert result.metrics.exposure_pct == pytest.approx(Decimal("25"), abs=Decimal("0.01"))
        assert result.metrics.benchmark_return_pct == Decimal("0")
        assert result.metrics.win_rate_pct == pytest.approx(Decimal("0"))

    def test_winning_trade_without_fees_matches_hand_math(self):
        # BUY decided at c1 (fills c2 open 90), SELL at c2 (fills c3 open 100).
        # base = floor(500/90, 1e-8) = 5.55555555 → proceeds 555.555555 → pnl +55.555555.
        result = run_with({1: "buy", 2: "sell"}, [(100, 100), (110, 110), (90, 90), (100, 100)])
        assert result.metrics.trade_count == 1
        trade = result.trades[0]
        assert trade.entry_price == Decimal("90")
        assert trade.exit_price == Decimal("100")
        assert trade.base_size == Decimal("5.55555555")
        assert trade.pnl_quote == pytest.approx(Decimal("55.5555555"), abs=Decimal("0.001"))
        net = pytest.approx(Decimal("5.5556"), abs=Decimal("0.001"))
        assert result.metrics.net_return_pct == net
        assert result.metrics.win_rate_pct == pytest.approx(Decimal("100"))
        # Rounding dust only — the floor-to-increment leaves a sub-cent wobble.
        assert result.metrics.max_drawdown_pct == pytest.approx(Decimal("0"), abs=Decimal("0.001"))
        assert result.metrics.profit_factor is None  # wins but no losses

    def test_end_of_data_force_close_is_labeled(self):
        result = run_with({0: "buy"}, [(100, 100), (110, 110), (120, 120)])
        assert result.metrics.trade_count == 1
        assert result.trades[0].note == END_OF_DATA
        assert result.trades[0].exit_price == Decimal("120")

    def test_all_in_position_size_cannot_exceed_cash(self):
        runner = BacktestEngine(
            strategy=ScriptedStrategy({0: "buy"}),
            assumptions=FeeAssumptions(fee_bps=10000.0),  # 100% fee: cost doubles
            initial_quote=Decimal("1000"),
            position_size_quote=Decimal("1000"),
        )
        config = EmaRsiConfig(product_id="BTC-USD", timeframe="1h")
        result = runner.run(candles_from([(100, 100), (110, 110), (120, 120)]), config)
        # Cash (1000) cannot cover 1000 notional + 1000 fee → entry skipped.
        assert result.metrics.trade_count == 0


class TestLookAhead:
    def test_decisions_before_a_future_candle_never_change(self):
        prefix = candles_from([(100, 100), (110, 110), (90, 90), (100, 100)])
        extra = Candle(
            product_id="BTC-USD",
            granularity="ONE_HOUR",
            start_time=START + 4 * HOURLY,
            open=Decimal(500),
            high=Decimal(501),
            low=Decimal(499),
            close=Decimal(500),
            volume=Decimal(1),
        )
        record_prefix: list = []
        record_full: list = []
        run_with(
            {0: "buy", 1: "sell"},
            [(100, 100), (110, 110), (90, 90), (100, 100)],
            record=record_prefix,
        )
        runner = engine()
        runner.strategy = ScriptedStrategy({0: "buy", 1: "sell"}, record=record_full)
        runner.run(
            [*prefix, extra], EmaRsiConfig(product_id="BTC-USD", timeframe="1h")
        )
        # Decisions on windows of length 1..4 are identical whether or not
        # the future candle exists → no look-ahead.
        assert record_prefix == record_full[: len(record_prefix)]

    def test_same_inputs_produce_identical_results(self):
        candles = candles_from([(100, 100), (110, 105), (95, 100), (105, 110), (100, 100)])
        config = EmaRsiConfig(product_id="BTC-USD", timeframe="1h")
        results = []
        for _ in range(3):
            runner = engine(fee_bps=100.0)
            runner.strategy = ScriptedStrategy({0: "buy", 2: "sell"})
            results.append(runner.run(candles, config))
        assert results[0] == results[1] == results[2]
