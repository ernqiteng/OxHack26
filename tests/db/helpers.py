"""Synthetic grid_raw rows for Girik's db tests. Dates in 2025 so the refresh/compression policies
(which look at the last 3-7 days) never touch test data. Independent of Ernqi's fixture on purpose."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from tempo.db.conn import refresh_caggs

MONDAY = datetime(2025, 1, 6, tzinfo=UTC)  # a Monday, in GMT so London == UTC


def mid_frame(start: datetime = MONDAY, days: int = 14, seed: int = 0, delay_min: int = 10) -> pd.DataFrame:
    """APX price + volume rows every 30 min: daily shape (cheap 01-05, dear 17-19) plus seeded noise."""
    n = days * 48
    st = pd.date_range(start, periods=n, freq="30min", tz=UTC)
    hour = st.hour + st.minute / 60
    shape = np.where((hour >= 1) & (hour < 5), -1.0, np.where((hour >= 17) & (hour < 19), 1.0, 0.0))
    rng = np.random.default_rng(seed)
    price = np.round(60 + 40 * shape + rng.normal(0, 5, n), 2)
    local = st.tz_convert("Europe/London")
    common = {
        "start_time": st,
        "available_at": st + pd.Timedelta(minutes=30 + delay_min),
        "dataset": "MID",
        "settlement_date": local.normalize().tz_localize(None),
        "settlement_period": (local - local.normalize()) // pd.Timedelta(minutes=30) + 1,
    }
    price_df = pd.DataFrame({**common, "series": "APXMIDP", "value": price})
    vol_df = pd.DataFrame({**common, "series": "APXMIDP:volume", "value": 100.0})
    return pd.concat([price_df, vol_df], ignore_index=True)


def windfor_frame(start: datetime = MONDAY, days: int = 14, seed: int = 1) -> pd.DataFrame:
    """Hourly WINDFOR published 2 h before each start hour."""
    n = days * 24
    st = pd.date_range(start, periods=n, freq="1h", tz=UTC)
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "start_time": st,
            "available_at": st - pd.Timedelta(hours=2),
            "dataset": "WINDFOR",
            "series": "",
            "value": np.round(rng.uniform(2000, 15000, n), 1),
            "settlement_date": None,
            "settlement_period": None,
        }
    )


def clean(conn, start: datetime, end: datetime) -> None:
    """Truncate grid_raw and re-refresh the caggs over the window so no materialised rows leak out.
    conftest's TRUNCATE alone does not clear continuous aggregates."""
    conn.execute("TRUNCATE grid_raw, ingest_log")  # conftest's list predates ingest_log
    refresh_caggs(conn, start - timedelta(days=7), end + timedelta(days=14))
