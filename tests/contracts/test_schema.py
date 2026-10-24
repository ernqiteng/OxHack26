"""Schema contract (docs/plan.md 2.1, docs/girik.md Phase 0). Needs the local Docker DB (dev_db.sh)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tempo.db.conn import SCHEMA_PATH, apply_schema, run_sql, upsert_grid_raw

HYPERTABLES = {"grid_raw", "forecasts", "decisions", "battery_state", "audits"}
CAGG_COLUMNS = {
    "prices_hh": {"bucket", "price", "volume"},
    "prices_daily": {"bucket", "mean", "min", "max", "spread", "n", "sum_price", "sum_sq"},
    "prices_weekly": {"bucket", "mean", "stddev", "spread_mean"},
}


@pytest.fixture
def schema_conn(db_conn):
    apply_schema(db_conn)
    return db_conn


def test_schema_file_has_no_dollar_bodies():
    assert "$$" not in SCHEMA_PATH.read_text(encoding="utf-8")


def test_schema_is_idempotent(schema_conn):
    apply_schema(schema_conn)  # second application must not raise


def test_hypertables(schema_conn):
    rows = run_sql(
        schema_conn,
        "SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema = 'public'",
    )
    assert {r[0] for r in rows} == HYPERTABLES


@pytest.mark.parametrize("table", ["backtest_results", "ingest_log"])
def test_plain_tables(schema_conn, table):
    rows = run_sql(
        schema_conn, "SELECT table_type FROM information_schema.tables WHERE table_name = %s", (table,)
    )
    assert rows == [("BASE TABLE",)]


def test_caggs_exist_and_are_hierarchical(schema_conn):
    defs = dict(
        run_sql(
            schema_conn,
            "SELECT view_name, view_definition FROM timescaledb_information.continuous_aggregates",
        )
    )
    assert set(defs) == set(CAGG_COLUMNS)
    assert "grid_raw" in defs["prices_hh"]
    assert "prices_hh" in defs["prices_daily"]
    assert "prices_daily" in defs["prices_weekly"]


def test_cagg_columns(schema_conn):
    for view, cols in CAGG_COLUMNS.items():
        rows = run_sql(
            schema_conn, "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (view,)
        )
        assert {r[0] for r in rows} == cols, view


def test_refresh_policies(schema_conn):
    rows = run_sql(
        schema_conn,
        "SELECT hypertable_name FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_refresh_continuous_aggregate'",
    )
    assert len(rows) == 3


def test_grid_raw_compression_enabled_with_policy(schema_conn):
    rows = run_sql(
        schema_conn,
        "SELECT compression_enabled FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = 'grid_raw'",
    )
    assert rows == [(True,)]
    jobs = run_sql(
        schema_conn,
        "SELECT hypertable_name FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression'",
    )
    assert jobs == [("grid_raw",)]
    settings = run_sql(
        schema_conn,
        "SELECT segmentby, orderby FROM timescaledb_information.hypertable_compression_settings "
        "WHERE hypertable = 'grid_raw'::regclass",
    )
    # TimescaleDB stores the lists without spaces
    assert [(s.replace(" ", ""), o.replace(" ", "")) for s, o in settings] == [
        ("dataset,series", "start_time,available_at")
    ]


def _refresh_all(conn, start, end):
    for view in ("prices_hh", "prices_daily", "prices_weekly"):
        conn.execute("CALL refresh_continuous_aggregate(%s, %s, %s)", (view, start, end))


def test_clock_change_day_aggregates(schema_conn):
    """2025-10-26 (clocks go back) is one London settlement day of 50 half-hours: UTC 2025-10-25 23:00
    to 2025-10-26 23:30. prices_daily must hold exactly one row for it with n = 50, and the weekly
    mean/stddev must equal numpy's over the same 50 prices."""
    conn = schema_conn
    first = datetime(2025, 10, 25, 23, 0, tzinfo=UTC)
    starts = [first + timedelta(minutes=30 * k) for k in range(50)]
    prices = np.round(50 + 30 * np.sin(np.arange(50) / 5.0), 2)
    df = pd.DataFrame(
        {
            "start_time": starts * 2,
            "available_at": [s + timedelta(minutes=40) for s in starts] * 2,
            "dataset": "MID",
            "series": ["APXMIDP"] * 50 + ["APXMIDP:volume"] * 50,
            "value": list(prices) + [100.0] * 50,
            "settlement_date": [pd.Timestamp("2025-10-26")] * 100,
            "settlement_period": list(range(1, 51)) * 2,
        }
    )
    window = (datetime(2025, 10, 6, tzinfo=UTC), datetime(2025, 11, 17, tzinfo=UTC))
    try:
        assert upsert_grid_raw(conn, df) == 100
        _refresh_all(conn, *window)

        hh = run_sql(conn, "SELECT count(*), count(DISTINCT bucket), sum(volume) FROM prices_hh")
        assert hh == [(50, 50, 5000.0)]

        daily = run_sql(conn, "SELECT bucket, n, min, max, spread FROM prices_daily ORDER BY bucket")
        assert len(daily) == 1
        bucket, n, mn, mx, spread = daily[0]
        assert bucket == first  # 2025-10-26 00:00 BST
        assert n == 50
        assert (mn, mx) == (prices.min(), prices.max())
        assert spread == pytest.approx(prices.max() - prices.min())

        weekly = run_sql(conn, "SELECT mean, stddev FROM prices_weekly")
        assert len(weekly) == 1
        assert weekly[0][0] == pytest.approx(prices.mean(), abs=1e-9)
        assert weekly[0][1] == pytest.approx(prices.std(ddof=1), abs=1e-9)
    finally:
        conn.execute("TRUNCATE grid_raw")
        _refresh_all(conn, *window)  # clear materialised buckets so later tests start empty
