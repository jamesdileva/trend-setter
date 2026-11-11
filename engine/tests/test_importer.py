"""End-to-end offline import tests (roadmap Sprint 4 verification).

Covers: exact row counts across windows, repeat-import dedup, gap
identification, invalid-candle quarantine, progress reporting, and
deterministic aggregation — all against fixture data, no network.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.database import CandleRepository, Database, upgrade_to_head
from trendbot.exchange.coinbase_rest import CandlePage
from trendbot.market_data.candles import Candle
from trendbot.market_data.importer import CandleImporter

START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "market.db")
    upgrade_to_head(database)
    return database


def synthetic_fetch(*, omit: set[datetime] | None = None, invalid_at: datetime | None = None):
    """Deterministic 1h candles for any window; prices derive from the hour."""
    omitted = omit or set()

    def fetch(w_start: datetime, w_end: datetime) -> CandlePage:
        candles: list[Candle] = []
        rejected: list[str] = []
        current = w_start
        while current < w_end:
            if current not in omitted:
                price = Decimal(100 + (int(current.timestamp()) // 3600) % 13)
                if invalid_at == current:
                    rejected.append("synthetic invalid candle (high below open)")
                else:
                    candles.append(
                        Candle(
                            product_id="BTC-USD",
                            granularity="ONE_HOUR",
                            start_time=current,
                            open=price,
                            high=price + Decimal(2),
                            low=price - Decimal(2),
                            close=price + Decimal(1),
                            volume=Decimal("1.5"),
                        )
                    )
            current += timedelta(hours=1)
        return CandlePage(candles=candles, rejected_reasons=rejected)

    return fetch


def minute_fetch(w_start: datetime, w_end: datetime) -> CandlePage:
    candles: list[Candle] = []
    current = w_start
    while current < w_end:
        price = Decimal(50 + (int(current.timestamp()) // 60) % 9)
        candles.append(
            Candle(
                product_id="BTC-USD",
                granularity="ONE_MINUTE",
                start_time=current,
                open=price,
                high=price + Decimal(1),
                low=price - Decimal(1),
                close=price,
                volume=Decimal("0.5"),
            )
        )
        current += timedelta(minutes=1)
    return CandlePage(candles=candles, rejected_reasons=[])


class TestImport:
    def test_fixture_imports_with_exact_row_counts(self, db):
        summary = CandleImporter(db).import_history(
            fetch_page=synthetic_fetch(),
            product_id="BTC-USD",
            timeframe="1h",
            start=START,
            end=START + timedelta(hours=48),
        )
        assert summary.imported == 48
        assert summary.requested_buckets == 48
        assert CandleRepository(db).count() == 48
        assert summary.missing_ranges == []

    def test_multi_window_import_spans_windows(self, db):
        summary = CandleImporter(db).import_history(
            fetch_page=minute_fetch,
            product_id="BTC-USD",
            timeframe="1m",
            start=START,
            end=START + timedelta(minutes=700),  # two windows of 350
        )
        assert summary.imported == 700
        assert CandleRepository(db).count() == 700

    def test_repeated_import_does_not_duplicate(self, db):
        importer = CandleImporter(db)
        kwargs = {
            "product_id": "BTC-USD",
            "timeframe": "1h",
            "start": START,
            "end": START + timedelta(hours=48),
        }
        first = importer.import_history(fetch_page=synthetic_fetch(), **kwargs)
        second = importer.import_history(fetch_page=synthetic_fetch(), **kwargs)
        assert first.imported == 48
        assert second.imported == 0
        assert second.duplicates == 48
        assert CandleRepository(db).count() == 48

    def test_missing_intervals_are_identified(self, db):
        gap = {
            START + timedelta(hours=7),
            START + timedelta(hours=8),
            START + timedelta(hours=20),
        }
        summary = CandleImporter(db).import_history(
            fetch_page=synthetic_fetch(omit=gap),
            product_id="BTC-USD",
            timeframe="1h",
            start=START,
            end=START + timedelta(hours=48),
        )
        assert (START + timedelta(hours=7), START + timedelta(hours=9)) in summary.missing_ranges
        assert (START + timedelta(hours=20), START + timedelta(hours=21)) in summary.missing_ranges
        assert len(summary.missing_ranges) == 2

    def test_invalid_candles_are_quarantined_and_reported_missing(self, db):
        bad_hour = START + timedelta(hours=5)
        summary = CandleImporter(db).import_history(
            fetch_page=synthetic_fetch(invalid_at=bad_hour),
            product_id="BTC-USD",
            timeframe="1h",
            start=START,
            end=START + timedelta(hours=48),
        )
        assert summary.rejected == 1
        assert summary.imported == 47
        assert CandleRepository(db).count() == 47
        assert (bad_hour, bad_hour + timedelta(hours=1)) in summary.missing_ranges

    def test_progress_reports_each_window(self, db):
        events: list[object] = []
        CandleImporter(db).import_history(
            fetch_page=synthetic_fetch(),
            product_id="BTC-USD",
            timeframe="1h",
            start=START,
            end=START + timedelta(hours=48),
            progress=events.append,
        )
        assert len(events) == 1

        minute_events: list[object] = []
        CandleImporter(db).import_history(
            fetch_page=minute_fetch,
            product_id="BTC-USD",
            timeframe="1m",
            start=START,
            end=START + timedelta(minutes=700),
            progress=minute_events.append,
        )
        assert len(minute_events) == 2
        assert minute_events[-1].windows_done == 2
        assert minute_events[-1].candles_new == 700

    def test_aggregated_import_matches_the_fixture(self, db):
        summary = CandleImporter(db).import_history(
            fetch_page=synthetic_fetch(),
            product_id="BTC-USD",
            timeframe="4h",
            from_timeframe="1h",
            start=START,
            end=START + timedelta(hours=12),
        )
        assert summary.imported == 3
        stored = CandleRepository(db).get_range(
            "BTC-USD", "FOUR_HOUR", START, START + timedelta(hours=12)
        )
        assert len(stored) == 3
        assert all(candle.is_complete for candle in stored)
        assert stored[0].start_time == START
        raw_source = db.execute_scalar(
            "SELECT source FROM candles WHERE granularity = 'FOUR_HOUR' LIMIT 1"
        )
        assert raw_source == "local_aggregated"

    def test_aggregated_partial_group_is_marked_incomplete(self, db):
        summary = CandleImporter(db).import_history(
            fetch_page=synthetic_fetch(),
            product_id="BTC-USD",
            timeframe="4h",
            from_timeframe="1h",
            start=START,
            end=START + timedelta(hours=14),
        )
        assert summary.imported == 4
        stored = CandleRepository(db).get_range(
            "BTC-USD", "FOUR_HOUR", START, START + timedelta(hours=14)
        )
        assert [candle.is_complete for candle in stored] == [True, True, True, False]
        assert summary.missing_ranges == []

    def test_naive_range_is_rejected(self, db):
        with pytest.raises(ValueError):
            CandleImporter(db).import_history(
                fetch_page=synthetic_fetch(),
                product_id="BTC-USD",
                timeframe="1h",
                start=datetime(2026, 1, 1),
                end=START + timedelta(hours=1),
            )
