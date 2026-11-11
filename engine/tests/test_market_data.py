"""Offline tests for granularity, aggregation, and gap detection (Sprint 4)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.market_data.aggregate import aggregate_candles
from trendbot.market_data.candles import Candle
from trendbot.market_data.gaps import expected_starts, find_missing_ranges
from trendbot.market_data.granularity import (
    TIMEFRAME_GRANULARITY,
    bucket_floor,
    granularity_for_timeframe,
    granularity_seconds,
)


def candle(
    start: datetime,
    open_: int,
    high: int,
    low: int,
    close: int,
    volume: int = 1,
    *,
    product_id: str = "BTC-USD",
    granularity: str = "ONE_HOUR",
) -> Candle:
    return Candle(
        product_id=product_id,
        granularity=granularity,
        start_time=start,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
    )


class TestGranularity:
    def test_roadmap_timeframes_map_to_verified_labels(self):
        assert TIMEFRAME_GRANULARITY == {
            "1m": "ONE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "1h": "ONE_HOUR",
            "4h": "FOUR_HOUR",
        }

    def test_seconds_match_the_verified_enum(self):
        assert granularity_seconds("ONE_MINUTE") == 60
        assert granularity_seconds("FIFTEEN_MINUTE") == 900
        assert granularity_seconds("FOUR_HOUR") == 14400
        assert granularity_seconds("ONE_DAY") == 86400

    def test_unknown_timeframe_error_is_plain_language(self):
        with pytest.raises(KeyError) as excinfo:
            granularity_for_timeframe("2m")
        assert "not supported" in str(excinfo.value)
        assert "1h" in str(excinfo.value)

    def test_bucket_floor_aligns_to_utc_boundaries(self):
        moment = datetime(2026, 3, 1, 13, 7, 45, tzinfo=UTC)
        assert bucket_floor(moment, 3600) == datetime(2026, 3, 1, 13, tzinfo=UTC)
        assert bucket_floor(moment, 14400) == datetime(2026, 3, 1, 12, tzinfo=UTC)
        assert bucket_floor(moment, 86400) == datetime(2026, 3, 1, tzinfo=UTC)

    def test_bucket_floor_rejects_naive_datetimes(self):
        with pytest.raises(ValueError):
            bucket_floor(datetime(2026, 3, 1), 3600)


class TestAggregation:
    @staticmethod
    def four_hourly() -> list[Candle]:
        base = datetime(2026, 1, 1, tzinfo=UTC)
        prices = [
            (100, 110, 95, 105, 1),
            (105, 120, 104, 118, 2),
            (118, 119, 90, 92, 3),
            (92, 130, 91, 125, 4),
        ]
        return [
            candle(base + timedelta(hours=index), *prices[index])
            for index in range(len(prices))
        ]

    def test_full_group_matches_hand_calculated_fixture(self):
        result = aggregate_candles(
            self.four_hourly(), from_granularity="ONE_HOUR", to_granularity="FOUR_HOUR"
        )
        assert len(result) == 1
        aggregated = result[0]
        assert aggregated.start_time == datetime(2026, 1, 1, tzinfo=UTC)
        assert aggregated.open == Decimal("100")
        assert aggregated.high == Decimal("130")
        assert aggregated.low == Decimal("90")
        assert aggregated.close == Decimal("125")
        assert aggregated.volume == Decimal("10")
        assert aggregated.is_complete is True
        assert aggregated.granularity == "FOUR_HOUR"

    def test_partial_group_is_marked_incomplete(self):
        result = aggregate_candles(
            self.four_hourly()[:3], from_granularity="ONE_HOUR", to_granularity="FOUR_HOUR"
        )
        assert result[0].is_complete is False
        assert result[0].close == Decimal("92")

    def test_multiple_groups_stay_ordered(self):
        candles = self.four_hourly() + [
            candle(datetime(2026, 1, 1, 4, tzinfo=UTC), 125, 126, 100, 101, 5),
            candle(datetime(2026, 1, 1, 5, tzinfo=UTC), 101, 111, 99, 108, 6),
        ]
        result = aggregate_candles(
            candles, from_granularity="ONE_HOUR", to_granularity="FOUR_HOUR"
        )
        assert len(result) == 2
        assert result[0].start_time == datetime(2026, 1, 1, tzinfo=UTC)
        assert result[0].is_complete is True
        assert result[1].start_time == datetime(2026, 1, 1, 4, tzinfo=UTC)
        assert result[1].is_complete is False
        assert result[1].high == Decimal("126")
        assert result[1].low == Decimal("99")

    def test_target_bucket_must_be_a_multiple_of_the_source(self):
        with pytest.raises(ValueError):
            aggregate_candles(
                self.four_hourly(), from_granularity="ONE_HOUR", to_granularity="ONE_MINUTE"
            )

    def test_mixed_source_granularity_is_rejected(self):
        candles = self.four_hourly()
        intruder = candle(
            datetime(2026, 1, 1, 9, tzinfo=UTC), 1, 2, 0, 1, granularity="FIVE_MINUTE"
        )
        with pytest.raises(ValueError):
            aggregate_candles(
                [*candles, intruder], from_granularity="ONE_HOUR", to_granularity="FOUR_HOUR"
            )


class TestGapDetection:
    def test_fully_covered_range_has_no_missing(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=5)
        present = expected_starts(start, end, 3600)
        assert find_missing_ranges(present, start, end, 3600) == []

    def test_consecutive_and_isolated_gaps_collapse_into_ranges(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=5)
        missing = [
            start + timedelta(hours=1),
            start + timedelta(hours=2),
            start + timedelta(hours=4),
        ]
        present = [
            bucket
            for bucket in expected_starts(start, end, 3600)
            if bucket not in missing
        ]
        ranges = find_missing_ranges(present, start, end, 3600)
        assert ranges == [
            (start + timedelta(hours=1), start + timedelta(hours=3)),
            (start + timedelta(hours=4), start + timedelta(hours=5)),
        ]

    def test_empty_present_reports_the_whole_range(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=3)
        assert find_missing_ranges([], start, end, 3600) == [(start, end)]

    def test_naive_datetimes_are_rejected(self):
        with pytest.raises(ValueError):
            find_missing_ranges([], datetime(2026, 1, 1), datetime(2026, 1, 2), 3600)
