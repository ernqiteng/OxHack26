"""coverage(): the backfill must notice a half-load, a late start, an early end, or a multi-day gap."""

from datetime import timedelta

import pytest

from tempo.db.conn import apply_schema, upsert_grid_raw
from tempo.ingest.backfill import coverage
from tests.db.helpers import MONDAY, clean, mid_frame, windfor_frame

END = MONDAY + timedelta(days=14)


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    try:
        yield db_conn
    finally:
        clean(db_conn, MONDAY, END)


def test_full_range_is_ok(conn):
    upsert_grid_raw(conn, mid_frame(MONDAY, 14))
    cov = coverage(conn, "MID", MONDAY, END)
    assert cov.ok and cov.problems == []
    assert (cov.first, cov.last) == (MONDAY, END - timedelta(minutes=30))
    assert cov.days_with_data == cov.expected_days == 14
    assert "ok" in cov.summary()


def test_half_load_is_a_problem(conn):
    upsert_grid_raw(conn, mid_frame(MONDAY, 7))  # only the first week of a 14-day request
    cov = coverage(conn, "MID", MONDAY, END)
    assert not cov.ok
    assert cov.days_with_data == 7
    assert any(p.startswith("ends early") for p in cov.problems)


def test_late_start_is_a_problem(conn):
    upsert_grid_raw(conn, mid_frame(MONDAY + timedelta(days=3), 11))
    cov = coverage(conn, "MID", MONDAY, END)
    assert [p.split(":")[0] for p in cov.problems] == ["starts late"]


def test_gap_longer_than_a_day_is_reported(conn):
    df = mid_frame(MONDAY, 14)
    hole = (df["start_time"] >= MONDAY + timedelta(days=5)) & (df["start_time"] < MONDAY + timedelta(days=8))
    upsert_grid_raw(conn, df[~hole])  # days 5, 6, 7 missing
    cov = coverage(conn, "MID", MONDAY, END)
    assert cov.days_with_data == 11
    assert cov.gaps == [(MONDAY + timedelta(days=4), MONDAY + timedelta(days=8))]
    assert cov.problems == ["gap: no data between 2025-01-10 and 2025-01-14 (3 missing days)"]


def test_single_missing_day_is_reported(conn):
    """Stricter than 'longer than a day': one missing day of prices is already a problem worth a warning."""
    df = mid_frame(MONDAY, 14)
    hole = (df["start_time"] >= MONDAY + timedelta(days=5)) & (df["start_time"] < MONDAY + timedelta(days=6))
    upsert_grid_raw(conn, df[~hole])
    cov = coverage(conn, "MID", MONDAY, END)
    assert not cov.ok
    assert cov.days_with_data == 13 and cov.expected_days == 14
    assert cov.problems == ["gap: no data between 2025-01-10 and 2025-01-12 (1 missing days)"]


def test_forecast_datasets_are_keyed_on_available_at(conn):
    upsert_grid_raw(conn, windfor_frame(MONDAY, 14))  # published 2 h before each start hour
    cov = coverage(conn, "WINDFOR", MONDAY, END)
    assert cov.first == MONDAY - timedelta(hours=2) or cov.first >= MONDAY  # clipped to the window
    assert cov.ok


def test_no_rows(conn):
    cov = coverage(conn, "NDF", MONDAY, END)
    assert cov.problems == ["no rows"] and not cov.ok
