"""storage_stats() for the dashboard's "X rows, compressed Y%" line (docs/girik.md Phase 3)."""

from datetime import timedelta

import pytest

from tempo.db.conn import apply_schema, upsert_grid_raw
from tempo.db.stats import compress_chunks, storage_stats
from tests.db.helpers import MONDAY, clean, forecast_frame, mid_frame

DAYS = 30


@pytest.fixture
def loaded(db_conn):
    """(conn, number of rows actually inserted): the independent row count the stats must report."""
    apply_schema(db_conn)
    inserted = upsert_grid_raw(db_conn, mid_frame(MONDAY, DAYS))
    inserted += upsert_grid_raw(db_conn, forecast_frame("NDF", MONDAY, DAYS, step="30min", series="N"))
    try:
        yield db_conn, inserted
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=DAYS))


def test_ratio_is_one_before_compression(loaded):
    conn, inserted = loaded
    s = storage_stats(conn)
    assert s["rows"] == inserted > 0
    assert s["compressed_chunks"] == 0
    assert s["ratio"] == 1.0 and s["pct_saved"] == 0.0


def test_ratio_above_one_after_compression(loaded):
    conn, inserted = loaded
    compress_chunks(conn)
    s = storage_stats(conn)
    assert s["rows"] == inserted  # compression keeps every row, and the count sees compressed chunks
    assert s["compressed_chunks"] == s["total_chunks"] > 0
    assert s["before_bytes"] > s["after_bytes"] > 0
    assert s["ratio"] == pytest.approx(s["before_bytes"] / s["after_bytes"])
    assert s["ratio"] > 1
    assert s["pct_saved"] == pytest.approx((1 - s["after_bytes"] / s["before_bytes"]) * 100)
    assert 0 < s["pct_saved"] < 100
    assert s["database_mb"] > 0
