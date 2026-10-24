"""Known answer (docs/girik.md Phase 2): price_lag_1d at target t equals prices_hh at t - 1 day exactly,
price_lag_7d at t - 7 days. Checked on the synthetic market and on real APX prices across the 26 Oct 2025
clock change (lags are elapsed UTC time: 24 h and 168 h)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, run_sql, upsert_grid_raw
from tempo.features.build import build_features
from tempo.ingest.elexon import normalise
from tests.db.helpers import MONDAY, clean, forecast_frame, market

REAL = (
    Path(__file__).resolve().parents[1] / "fixtures" / "elexon_samples" / "MID_APX_2025-10-01_2025-11-12.json"
)


def prices_hh(conn) -> dict:
    return {pd.Timestamp(b): p for b, p in run_sql(conn, "SELECT bucket, price FROM prices_hh")}


def check_lags(conn, decision_time):
    f = build_features(conn, decision_time)
    hh = prices_hh(conn)
    cutoff = pd.Timestamp(decision_time) - pd.Timedelta(minutes=40)  # MID delay 10
    checked = 0
    for t, row in f.iterrows():
        for col, lag in (("price_lag_1d", pd.Timedelta(days=1)), ("price_lag_7d", pd.Timedelta(days=7))):
            src = t - lag
            if src <= cutoff and src in hh:
                assert row[col] == hh[src], (t, col, row[col], hh[src])  # exact, not approx
                checked += 1
            else:  # not yet published at decision time: falls back to the last known price, flagged
                assert row[col] == row["price_last_known"] and row["lag_missing"] == 1.0, (t, col)
    return f, checked


@pytest.fixture
def synthetic(db_conn):
    apply_schema(db_conn)
    market(db_conn, MONDAY, 30)
    try:
        yield db_conn
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=30))


def test_lags_equal_prices_hh_on_synthetic(synthetic):
    T = MONDAY + timedelta(days=23, hours=12, minutes=10)
    f, checked = check_lags(synthetic, T)
    assert checked == 48 + 47  # every 7-day lag, and every 1-day lag but the last target's
    # The last target is 24 h after 12:00 today, whose price is published at 12:40, after T = 12:10.
    assert f["lag_missing"].tolist() == [0.0] * 47 + [1.0]


@pytest.fixture
def real(db_conn):
    apply_schema(db_conn)
    start, end = datetime(2025, 10, 1, tzinfo=UTC), datetime(2025, 11, 12, tzinfo=UTC)
    upsert_grid_raw(db_conn, normalise("MID", json.loads(REAL.read_text(encoding="utf-8")), mid_delay=10))
    upsert_grid_raw(db_conn, forecast_frame("WINDFOR", start, 42, step="1h"))
    upsert_grid_raw(db_conn, forecast_frame("NDF", start, 42, step="30min", series="N"))
    refresh_caggs(db_conn, start - timedelta(days=7), end + timedelta(days=14))
    try:
        yield db_conn
    finally:
        clean(db_conn, start, end)


@pytest.mark.parametrize(
    "decision",
    [
        datetime(2025, 10, 25, 20, 10, tzinfo=UTC),  # Saturday evening: the horizon crosses the clock change
        datetime(
            2025, 10, 27, 7, 40, tzinfo=UTC
        ),  # Monday after: 1-day lags reach back into the 50-period day
        datetime(2025, 11, 2, 23, 55, tzinfo=UTC),  # 7-day lags reach back across the change
    ],
)
def test_lags_equal_prices_hh_on_real_prices(real, decision):
    _, checked = check_lags(real, decision)
    assert checked >= 90
