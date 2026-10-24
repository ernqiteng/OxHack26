from datetime import UTC, datetime, timedelta

import pytest

from tempo.ingest.elexon import DATASETS, chunk_range, window_params


def test_60_day_windows_tile_730_days():
    start = datetime(2024, 10, 24, tzinfo=UTC)
    end = start + timedelta(days=730)
    windows = list(chunk_range(start, end, 60))
    assert windows[0][0] == start
    assert windows[-1][1] == end
    for (_s, e), (s2, _) in zip(windows, windows[1:], strict=False):
        assert e == s2  # contiguous, non-overlapping
    assert all(e - s <= timedelta(days=60) for s, e in windows)
    assert len(windows) == 13  # 12 full + one 10-day remainder
    assert windows[-1][1] - windows[-1][0] == timedelta(days=10)


def test_7_day_windows_never_exceed_7_days():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for s, e in chunk_range(start, start + timedelta(days=100), 7):
        assert e - s <= timedelta(days=7)


def test_empty_and_invalid():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    assert list(chunk_range(t, t, 7)) == []
    with pytest.raises(ValueError):
        list(chunk_range(t, t + timedelta(days=1), 0))


def test_window_params_per_dataset():
    s, e = datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 8, tzinfo=UTC)
    assert window_params(DATASETS["MID"], s, e) == {
        "from": "2026-03-01T00:00:00Z",
        "to": "2026-03-08T00:00:00Z",
    }
    assert window_params(DATASETS["NDF"], s, e) == {
        "publishDateTimeFrom": "2026-03-01T00:00:00Z",
        "publishDateTimeTo": "2026-03-08T00:00:00Z",
    }
    assert window_params(DATASETS["INDO"], s, e) == {
        "settlementDateFrom": "2026-03-01",
        "settlementDateTo": "2026-03-07",  # inclusive dates, so [s, e) ends the day before
    }
    with pytest.raises(ValueError):
        window_params(DATASETS["DISEBSP"], s, e)
    with pytest.raises(ValueError, match="timezone-aware"):
        window_params(DATASETS["MID"], datetime(2026, 3, 1), e)
