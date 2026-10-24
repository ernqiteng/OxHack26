"""tempo.db.conn against the local Docker DB (scripts/dev_db.sh)."""

import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tempo.db.conn import GRID_RAW_COLUMNS, apply_schema, copy_rows, grid_raw_rows, run_sql, upsert_grid_raw

# 2025 dates: outside the refresh policies' 3-day window, so background jobs never materialise test rows.
T0 = datetime(2025, 1, 6, tzinfo=UTC)


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    return db_conn


def _frame(n: int, tz=UTC) -> pd.DataFrame:
    starts = pd.date_range(T0, periods=n, freq="30min", tz=UTC).tz_convert(tz)
    return pd.DataFrame(
        {
            "start_time": starts,
            "available_at": starts + pd.Timedelta(minutes=40),
            "dataset": "MID",
            "series": "APXMIDP",
            "value": [float(i % 97) for i in range(n)],
            "settlement_date": starts.tz_convert("Europe/London").normalize().tz_localize(None),
            "settlement_period": [i % 48 + 1 for i in range(n)],
        }
    )


def _count(conn) -> int:
    return run_sql(conn, "SELECT count(*) FROM grid_raw")[0][0]


def test_copy_rows_10k_under_2s(conn):
    rows = grid_raw_rows(_frame(10_000))
    t = time.perf_counter()
    n = copy_rows(conn, "grid_raw", rows, GRID_RAW_COLUMNS)
    elapsed = time.perf_counter() - t
    assert n == 10_000
    assert _count(conn) == 10_000
    assert elapsed < 2.0, f"COPY of 10k rows took {elapsed:.2f}s"


def test_upsert_grid_raw_is_idempotent(conn):
    df = _frame(1_000)
    assert upsert_grid_raw(conn, df) == 1_000
    assert upsert_grid_raw(conn, df) == 0
    assert _count(conn) == 1_000


def test_upsert_keeps_new_publication_of_same_period(conn):
    """A re-publication (same start_time, later available_at) is a new row, not a duplicate."""
    df = _frame(10)
    upsert_grid_raw(conn, df)
    later = df.assign(available_at=df["available_at"] + timedelta(hours=1), value=df["value"] + 1)
    assert upsert_grid_raw(conn, later) == 10
    assert _count(conn) == 20


def test_upsert_empty_frame_is_a_noop(conn):
    from tempo.ingest.elexon import normalise

    assert upsert_grid_raw(conn, normalise("MID", [])) == 0  # empty window from the API
    assert upsert_grid_raw(conn, _frame(0)) == 0
    assert _count(conn) == 0


def test_upsert_rejects_naive_timestamps(conn):
    df = _frame(5)
    df["start_time"] = df["start_time"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        upsert_grid_raw(conn, df)
    assert _count(conn) == 0


def test_upsert_converts_other_timezones_to_utc(conn):
    upsert_grid_raw(conn, _frame(3, tz="Europe/London"))
    stored = [r[0] for r in run_sql(conn, "SELECT start_time FROM grid_raw ORDER BY 1")]
    assert stored == [T0 + timedelta(minutes=30 * k) for k in range(3)]
