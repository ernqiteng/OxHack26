"""Adversarial point-in-time test for build_features, one case per feature column that reads data.

The setup is a synthetic month where MID stops two hours before the decision time T, and WINDFOR / NDF
are re-published every 6 h (publications after T already sit in the database, as in any backtest).

1. FUTURE rows must change nothing. For every column:
   - a MID price for the period starting at T floored (available at +40 min, i.e. after T), value 9999;
   - a WINDFOR and an NDF publication at T + 1 min for every target hour, value 99999.
2. PAST rows must change the column they feed (proves each case is sensitive, not vacuous):
   - MID at T - 40 min, available exactly at T (the inclusive boundary) -> last price, its age, the 24 h lag;
   - an earlier price edited -> the 168 h lag; yesterday's max edited -> the daily spread;
   - a price in the last complete week edited -> weekly mean and std;
   - WINDFOR / NDF publications at T - 1 min -> wind, demand and their ratio.

Mutation check (run by hand, results in the phase report): deleting any one `-- pit` line in
tempo/features/build.py makes test_future_rows_change_nothing fail.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, run_sql, upsert_grid_raw
from tempo.features.build import FEATURE_COLUMNS, build_features
from tests.db.helpers import MONDAY, clean, market

DAYS = 30
T = MONDAY + timedelta(days=23, hours=12, minutes=10)  # Wed 29 Jan 2025 12:10 UTC (GMT)
T0 = pd.Timestamp(T).floor("30min").to_pydatetime()  # 12:00
DELAY = 10  # the MID delay the synthetic rows are stamped with (mid_frame default)

# Which columns read the database, and which past row must move each of them.
DATA_COLUMNS = {
    "price_lag_1d": "boundary MID row",
    "price_lag_7d": "edited 168 h-ago price",
    "price_last_known": "boundary MID row",
    "hours_since_last_price": "boundary MID row",
    "daily_spread_lag_1d": "edited yesterday max",
    "weekly_mean": "edited last-week price",
    "weekly_std": "edited last-week price",
    "wind_fc": "WINDFOR at T-1min",
    "demand_fc": "NDF at T-1min",
    "wind_share_fc": "WINDFOR/NDF at T-1min",
    "lag_missing": "boundary MID row fills the 24 h lag",
}
CALENDAR_COLUMNS = ["hour", "dow", "is_weekend", "period_of_day"]


def _mid(start, value):
    start = pd.Timestamp(start)
    return pd.DataFrame(
        {
            "start_time": [start, start],
            "available_at": [start + pd.Timedelta(minutes=30 + DELAY)] * 2,
            "dataset": "MID",
            "series": ["APXMIDP", "APXMIDP:volume"],
            "value": [value, 100.0],
        }
    )


def _publication(dataset, published, value, series, step):
    targets = pd.date_range(T0 + pd.Timedelta(step), T0 + pd.Timedelta(hours=48), freq=step, tz="UTC")
    return pd.DataFrame(
        {"start_time": targets, "available_at": pd.Timestamp(published), "dataset": dataset, "series": series,
         "value": value}
    )  # fmt: skip


def _set_price(conn, start, value):
    conn.execute(
        "UPDATE grid_raw SET value = %s WHERE dataset = 'MID' AND series = 'APXMIDP' AND start_time = %s",
        (value, start),
    )


def _refresh(conn):
    refresh_caggs(conn, MONDAY - timedelta(days=7), MONDAY + timedelta(days=DAYS + 14))


@pytest.fixture(scope="module")
def frames():
    """(baseline, after future rows, after past rows) feature frames, computed once."""
    import os

    import psycopg

    url = os.environ.get("TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres")
    try:
        conn = psycopg.connect(url, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local test DB not reachable ({exc}); run scripts/dev_db.sh")
    apply_schema(conn)
    try:
        market(conn, MONDAY, DAYS, mid_until=T - timedelta(hours=2))
        base = build_features(conn, T)

        # 1. Future rows.
        upsert_grid_raw(conn, _mid(T0, 9999.0))  # available at 12:40 > T
        upsert_grid_raw(conn, _publication("WINDFOR", T + timedelta(minutes=1), 99999.0, "", "1h"))
        upsert_grid_raw(conn, _publication("NDF", T + timedelta(minutes=1), 99999.0, "N", "30min"))
        _refresh(conn)
        future = build_features(conn, T)

        # 2. Past rows.
        boundary = T0 - timedelta(minutes=30)  # 11:30, available at 12:10 == T exactly
        upsert_grid_raw(conn, _mid(boundary, 7777.0))
        _set_price(conn, pd.Timestamp(base.index[0]) - pd.Timedelta(days=7), 5555.0)  # 168 h before target 1
        yesterday = run_sql(
            conn,
            "SELECT start_time FROM grid_raw WHERE dataset='MID' AND series='APXMIDP' "
            "AND start_time >= %s AND start_time < %s ORDER BY value DESC LIMIT 1",
            (T0 - timedelta(hours=36), T0 - timedelta(hours=12)),  # Tue 00:00 to Tue 24:00 (GMT)
        )[0][0]
        _set_price(conn, yesterday, 8888.0)
        _set_price(conn, MONDAY + timedelta(days=15, hours=18), 4444.0)  # Tue 21 Jan, last complete week
        upsert_grid_raw(conn, _publication("WINDFOR", T - timedelta(minutes=1), 12345.0, "", "1h"))
        upsert_grid_raw(conn, _publication("NDF", T - timedelta(minutes=1), 23456.0, "N", "30min"))
        _refresh(conn)
        past = build_features(conn, T)
        yield base, future, past
    finally:
        clean(conn, MONDAY, MONDAY + timedelta(days=DAYS))
        conn.close()


@pytest.mark.parametrize("column", FEATURE_COLUMNS)
def test_future_rows_change_nothing(frames, column):
    base, future, _ = frames
    pd.testing.assert_series_equal(base[column], future[column], check_exact=True)


@pytest.mark.parametrize("column", sorted(DATA_COLUMNS))
def test_past_rows_change_the_column(frames, column):
    _, future, past = frames
    assert not np.array_equal(future[column].to_numpy(), past[column].to_numpy()), (
        f"{column} did not react to {DATA_COLUMNS[column]}: the leak test would be vacuous for it"
    )


def test_boundary_row_available_exactly_at_T_is_used(frames):
    """available_at == decision_time counts as available (<=, not <)."""
    _, future, past = frames
    assert past["price_last_known"].iloc[0] == 7777.0
    assert future["price_last_known"].iloc[0] != 7777.0


@pytest.mark.parametrize("column", CALENDAR_COLUMNS)
def test_calendar_columns_read_no_data(frames, column):
    base, future, past = frames
    assert base[column].equals(future[column]) and future[column].equals(past[column])


def test_every_column_is_covered():
    assert set(DATA_COLUMNS) | set(CALENDAR_COLUMNS) | {"fc_missing"} == set(FEATURE_COLUMNS)
