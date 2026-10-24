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


def forecast_frame(
    dataset: str,
    start: datetime = MONDAY,
    days: int = 14,
    step: str = "1h",
    publish_every_h: int = 6,
    horizon_h: int = 48,
    series: str = "",
) -> pd.DataFrame:
    """Re-published forecasts like the real WINDFOR / NDF: a publication every `publish_every_h` hours,
    each covering the next `horizon_h` hours at `step`. Each publication revises the value slightly, so
    "which publication was current at decision time" changes the answer (forecast versioning matters).
    Publications start 2 days before `start` so the first targets already have forecasts."""
    pubs = pd.date_range(
        start - timedelta(days=2), start + timedelta(days=days), freq=f"{publish_every_h}h", tz=UTC
    )
    frames = []
    for i, pub in enumerate(pubs):
        st = pd.date_range(pub + pd.Timedelta(step), pub + pd.Timedelta(hours=horizon_h), freq=step, tz=UTC)
        hour = st.hour + st.minute / 60
        base = (
            8000 + 3000 * np.sin(2 * np.pi * hour / 24)
            if dataset == "WINDFOR"
            else 30000 + 5000 * np.sin(2 * np.pi * (hour - 6) / 24)
        )
        frames.append(
            pd.DataFrame(
                {
                    "start_time": st,
                    "available_at": pub,
                    "dataset": dataset,
                    "series": series,
                    "value": np.round(base + (i % 7) * 11.0, 1),
                    "settlement_date": None,
                    "settlement_period": None,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def market(conn, start: datetime = MONDAY, days: int = 30, mid_until: datetime | None = None) -> None:
    """Load a synthetic market for feature tests: MID (optionally only up to mid_until), WINDFOR hourly and
    NDF half-hourly re-published every 6 h, then refresh all three aggregates."""
    from tempo.db.conn import upsert_grid_raw

    mid = mid_frame(start, days)
    if mid_until is not None:
        mid = mid[mid["start_time"] <= mid_until]
    upsert_grid_raw(conn, mid)
    upsert_grid_raw(conn, forecast_frame("WINDFOR", start, days, step="1h"))
    upsert_grid_raw(conn, forecast_frame("NDF", start, days, step="30min", series="N"))
    refresh_caggs(conn, start - timedelta(days=7), start + timedelta(days=days + 14))


def clean(conn, start: datetime, end: datetime) -> None:
    """Truncate grid_raw and re-refresh the caggs over the window so no materialised rows leak out.
    conftest's TRUNCATE alone does not clear continuous aggregates."""
    conn.execute("TRUNCATE grid_raw, ingest_log")  # conftest's list predates ingest_log
    refresh_caggs(conn, start - timedelta(days=7), end + timedelta(days=14))
