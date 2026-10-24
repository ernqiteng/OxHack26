"""prices_hh / prices_daily / prices_weekly against an independent pandas computation (girik.md Phase 1)."""

from datetime import timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, run_sql, upsert_grid_raw
from tests.db.helpers import MONDAY, clean, mid_frame

DAYS = 14
END = MONDAY + timedelta(days=DAYS)


@pytest.fixture
def loaded(db_conn):
    apply_schema(db_conn)
    df = mid_frame(MONDAY, DAYS)
    try:
        upsert_grid_raw(db_conn, df)
        refresh_caggs(db_conn, MONDAY - timedelta(days=7), END + timedelta(days=7))
        yield db_conn, df[df["series"] == "APXMIDP"].set_index("start_time")["value"].sort_index()
    finally:
        clean(db_conn, MONDAY, END)


def test_prices_hh_equals_pandas_resample(loaded):
    conn, price = loaded
    rows = run_sql(conn, "SELECT bucket, price, volume FROM prices_hh ORDER BY bucket")
    hh = pd.Series({r[0]: r[1] for r in rows}).sort_index()
    hh.index = pd.DatetimeIndex(hh.index).tz_convert("UTC")
    expected = price.resample("30min").mean()
    assert len(hh) == DAYS * 48
    pd.testing.assert_series_equal(hh.round(2), expected.round(2), check_names=False, check_freq=False)
    assert all(r[2] == 100.0 for r in rows)


def test_prices_daily_spread_is_max_minus_min(loaded):
    conn, price = loaded
    rows = run_sql(conn, "SELECT bucket, mean, min, max, spread, n FROM prices_daily ORDER BY bucket")
    assert len(rows) == DAYS
    by_day = price.groupby(price.index.tz_convert("Europe/London").date)
    expected = pd.DataFrame(
        {"mean": by_day.mean(), "min": by_day.min(), "max": by_day.max(), "n": by_day.size()}
    )
    for (bucket, mean, mn, mx, spread, n), (day, exp) in zip(rows, expected.iterrows(), strict=True):
        assert bucket.date() == day
        assert n == exp["n"] == 48
        assert (mn, mx) == (exp["min"], exp["max"])
        assert spread == pytest.approx(exp["max"] - exp["min"])
        assert mean == pytest.approx(exp["mean"])


def test_prices_weekly_two_rows_with_exact_stddev(loaded):
    conn, price = loaded
    rows = run_sql(conn, "SELECT bucket, mean, stddev, spread_mean FROM prices_weekly ORDER BY bucket")
    assert len(rows) == 2
    for i, (bucket, mean, std, spread_mean) in enumerate(rows):
        week = price[
            (price.index >= MONDAY + timedelta(days=7 * i))
            & (price.index < MONDAY + timedelta(days=7 * (i + 1)))
        ]
        assert bucket == MONDAY + timedelta(days=7 * i)
        assert len(week) == 336
        assert mean == pytest.approx(week.mean(), abs=1e-9)
        assert std == pytest.approx(week.std(ddof=1), abs=1e-9)  # stddev over half-hours, not of daily means
        daily = week.groupby(week.index.tz_convert("Europe/London").date)
        assert spread_mean == pytest.approx((daily.max() - daily.min()).mean(), abs=1e-9)
