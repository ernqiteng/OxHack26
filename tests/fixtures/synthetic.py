"""make_synthetic_market(days=60, seed=0) -> grid_raw-format DataFrame with known answers in this docstring.

Owner: Ernqi (Phase 0). See docs/ernqi.md.

Rows follow the grid_raw contract (docs/plan.md 2.1) and girik.md's normalise() rules:

    dataset   series     cadence   value          available_at
    MID       APXMIDP    30 min    price GBP/MWh  start_time + 30 min + delay (delay_min, default 10)
    WINDFOR   ''         60 min    wind MW        start_time - 30 min
    NDF       N          30 min    demand MW      start_time - 30 min

Price model (all clock rules use UK local time, Europe/London):
    price = 60 + 40 * shape(period) + noise N(0, 5)
    shape = -1 from 01:00 to 05:00 (night), +1 from 17:00 to 19:00 (peak), 0 otherwise
    even ISO weeks are "windy": night price -30 and WINDFOR high
    weekend peak -15

The default start (Mon 5 Jan 2026) with 60 days stays clear of clock changes, so every day has
exactly 48 periods. Same seed -> identical frame.

Known answers (7 days, default Battery, default seed), filled in once simulate() exists (Phase 1):
    perfect-foresight profit: TODO GBP
    simple-rule profit:       TODO GBP
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

UK = "Europe/London"
COLUMNS = ["start_time", "available_at", "dataset", "series", "value", "settlement_date", "settlement_period"]


def _local_clock(start_time: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return start_time.tz_convert(UK)


def _settlement(start_time: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Settlement date and period: half-hours since UK local midnight + 1 (never from the UTC clock)."""
    local = _local_clock(start_time)
    local_midnight = local.normalize()  # tz-aware, DST-correct
    period = ((start_time - local_midnight.tz_convert("UTC")) // pd.Timedelta(minutes=30)).astype(int) + 1
    return local.date, period.to_numpy(dtype=np.int16)


def make_synthetic_market(
    days: int = 60,
    seed: int = 0,
    start: datetime = datetime(2026, 1, 5, tzinfo=UTC),
    delay_min: int = 10,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(start).tz_convert("UTC")

    # --- MID price, half-hourly ------------------------------------------------
    hh = pd.date_range(start, periods=days * 48, freq="30min", tz="UTC")
    local = _local_clock(hh)
    hour = local.hour + local.minute / 60
    night = (hour >= 1) & (hour < 5)
    peak = (hour >= 17) & (hour < 19)
    windy = local.isocalendar().week.to_numpy(dtype=int) % 2 == 0
    weekend = local.day_of_week >= 5

    shape = np.where(night, -1.0, np.where(peak, 1.0, 0.0))
    price = 60 + 40 * shape
    price = price - 30 * (windy & night)
    price = price - 15 * (weekend & peak)
    price = price + rng.normal(0, 5, len(hh))

    # --- NDF demand, half-hourly, tracks the evening peak ----------------------
    demand = 25_000 + 10_000 * peak - 5_000 * night - 2_000 * weekend + rng.normal(0, 500, len(hh))

    # --- WINDFOR, hourly, high on windy weeks ----------------------------------
    hourly = pd.date_range(start, periods=days * 24, freq="60min", tz="UTC")
    windy_h = _local_clock(hourly).isocalendar().week.to_numpy(dtype=int) % 2 == 0
    wind = np.clip(np.where(windy_h, 12_000, 4_000) + rng.normal(0, 800, len(hourly)), 0, None)

    def frame(dataset, series, times, values, available_at):
        settlement_date, settlement_period = _settlement(times)
        return pd.DataFrame(
            {
                "start_time": times,
                "available_at": available_at,
                "dataset": dataset,
                "series": series,
                "value": np.asarray(values, dtype=float),
                "settlement_date": settlement_date,
                "settlement_period": settlement_period,
            }
        )

    out = pd.concat(
        [
            frame("MID", "APXMIDP", hh, price, hh + timedelta(minutes=30 + delay_min)),
            frame("WINDFOR", "", hourly, wind, hourly - timedelta(minutes=30)),
            frame("NDF", "N", hh, demand, hh - timedelta(minutes=30)),
        ],
        ignore_index=True,
    )
    return out.sort_values(["start_time", "dataset"], ignore_index=True)[COLUMNS]
