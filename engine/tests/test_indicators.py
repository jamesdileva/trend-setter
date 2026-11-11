"""Hand-calculated reference fixtures for the indicators (Sprint 6 verification)."""

from decimal import Decimal

import pytest

from trendbot.strategies.indicators.ema import ema
from trendbot.strategies.indicators.rsi import rsi


def closes(*values: int) -> list[Decimal]:
    return [Decimal(value) for value in values]


class TestEma:
    def test_hand_calculated_fixture(self):
        # k = 2/(3+1) = 0.5; seed = SMA(2,4,6) = 4; next: (8-4)*0.5+4 = 6.
        result = ema(closes(2, 4, 6, 8), 3)
        assert result == [None, None, pytest.approx(4.0), pytest.approx(6.0)]

    def test_second_fixture(self):
        # k = 2/3; seed = 15; next: (30-15)*2/3 + 15 = 25.
        result = ema(closes(10, 20, 30), 2)
        assert result == [None, pytest.approx(15.0), pytest.approx(25.0)]

    def test_constant_series_stays_exactly_at_the_constant(self):
        result = ema(closes(*([100] * 8)), 4)
        assert all(value == pytest.approx(100.0) for value in result[3:])
        assert result[:3] == [None, None, None]

    def test_warmup_leading_nones_and_output_length(self):
        result = ema(closes(1, 2, 3, 4, 5), 3)
        assert len(result) == 5
        assert result[0] is None and result[1] is None
        assert result[2] is not None

    def test_insufficient_history_is_all_none(self):
        assert ema(closes(1, 2), 3) == [None, None]

    def test_period_below_one_is_rejected(self):
        with pytest.raises(ValueError):
            ema(closes(1), 0)


class TestRsi:
    def test_hand_calculated_wilder_fixture(self):
        # Changes: +2, -1, +3, -1, +3; period 3.
        # idx3: gains 5/3, losses 1/3 → RS 5 → RSI = 100 - 100/6 ≈ 83.33
        # idx4: gains 10/9, losses 5/9 → RS 2 → RSI = 100 - 100/3 ≈ 66.67
        # idx5: gains 47/27, losses 10/27 → RS 4.7 → RSI = 100 - 100/5.7 ≈ 82.46
        result = rsi(closes(100, 102, 101, 104, 103, 106), 3)
        assert result[0] is None and result[1] is None and result[2] is None
        assert result[3] == pytest.approx(100 - 100 / 6)
        assert result[4] == pytest.approx(100 - 100 / 3)
        assert result[5] == pytest.approx(100 - 100 / 5.7)

    def test_flat_series_is_neutral_fifty(self):
        result = rsi(closes(*([100] * 8)), 5)
        assert result[:5] == [None] * 5
        assert result[5:] == [pytest.approx(50.0)] * 3

    def test_monotonic_up_reaches_100(self):
        result = rsi(closes(1, 2, 3, 4, 5, 6, 7), 3)
        assert result[-1] == pytest.approx(100.0)

    def test_monotonic_down_reaches_0(self):
        result = rsi(closes(7, 6, 5, 4, 3, 2, 1), 3)
        assert result[-1] == pytest.approx(0.0)

    def test_warmup_length(self):
        result = rsi(closes(100, 102, 101, 104), 2)
        assert len(result) == 4
        assert result[0] is None and result[1] is None
        assert result[2] is not None

    def test_period_below_one_is_rejected(self):
        with pytest.raises(ValueError):
            rsi(closes(1, 2), 0)

    def test_deterministic_repeats(self):
        values = closes(100, 102, 101, 104, 103, 106)
        assert rsi(values, 3) == rsi(values, 3)
        assert ema(values, 3) == ema(values, 3)
