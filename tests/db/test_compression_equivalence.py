"""Compressed chunks return exactly the same rows as uncompressed (docs/girik.md Phase 3, pulled into Phase 1
because the backfill now compresses as it goes). Also storage_stats() after compression."""

from datetime import timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, run_sql, upsert_grid_raw
from tempo.db.stats import chunk_residue, compress_chunks, storage_stats
from tests.db.helpers import MONDAY, clean, mid_frame, windfor_frame

DAYS = 30
END = MONDAY + timedelta(days=DAYS)
SNAPSHOT = (
    "SELECT start_time, available_at, dataset, series, value, settlement_date, settlement_period "
    "FROM grid_raw ORDER BY 1,2,3,4"
)


def snapshot(conn) -> pd.DataFrame:
    return pd.DataFrame(
        run_sql(conn, SNAPSHOT),
        columns=["start_time", "available_at", "dataset", "series", "value", "sd", "sp"],
    )


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    try:
        yield db_conn
    finally:
        clean(db_conn, MONDAY, END)


def test_compressed_rows_equal_uncompressed(conn):
    upsert_grid_raw(conn, mid_frame(MONDAY, DAYS))
    upsert_grid_raw(conn, windfor_frame(MONDAY, DAYS))
    before = snapshot(conn)
    assert len(before) == DAYS * 48 * 2 + DAYS * 24

    n = compress_chunks(conn)
    stats = storage_stats(conn)
    assert n == stats["total_chunks"] == stats["compressed_chunks"] >= 4
    assert stats["ratio"] > 1
    assert stats["pct_saved"] > 0

    after = snapshot(conn)
    pd.testing.assert_frame_equal(before, after)

    # Point lookups and the cagg filter path hit the compressed chunks too.
    (cnt,) = run_sql(conn, "SELECT count(*) FROM grid_raw WHERE dataset='MID' AND series='APXMIDP'")[0]
    assert cnt == DAYS * 48


def test_insert_into_compressed_chunk_then_recompress(conn):
    upsert_grid_raw(conn, windfor_frame(MONDAY, DAYS))
    compress_chunks(conn)
    fresh = chunk_residue(conn)
    assert fresh["heap_rows"] == 0
    # A second, denser dataset lands in already-compressed chunks (the cross-dataset backfill case).
    assert upsert_grid_raw(conn, mid_frame(MONDAY, DAYS)) == DAYS * 48 * 2
    dirty = chunk_residue(conn)
    assert dirty["heap_rows"] == DAYS * 48 * 2  # sits uncompressed until the next compress_chunks()
    expected = snapshot(conn)
    compress_chunks(conn)  # recompresses the partially compressed chunks and reindexes them
    clean_ = chunk_residue(conn)
    assert clean_["heap_rows"] == 0
    # No stale index pages left behind: within one 8 kB page per chunk of the freshly compressed size.
    assert clean_["index_bytes"] <= fresh["index_bytes"] + 8192 * fresh["compressed_chunks"], (fresh, clean_)
    pd.testing.assert_frame_equal(snapshot(conn), expected)
    stats = storage_stats(conn)
    assert stats["compressed_chunks"] == stats["total_chunks"]
    assert stats["rows"] == len(expected)


def test_storage_stats_keys(conn):
    s = storage_stats(conn)
    assert set(s) >= {
        "rows",
        "total_chunks",
        "compressed_chunks",
        "before_bytes",
        "after_bytes",
        "ratio",
        "pct_saved",
        "database_mb",
    }
    assert s["rows"] == 0 and s["ratio"] == 1.0
