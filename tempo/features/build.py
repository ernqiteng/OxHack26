"""build_features(conn, decision_time, horizon=48) -> DataFrame, using only rows available at decision_time.

Owner: Girik. See docs/girik.md Phase 2 and docs/todo_girik.md items 3 to 5.

Point-in-time rules (the guarantee every honesty number rests on):

- Forecast features (WINDFOR, NDF) read grid_raw directly with `available_at <= decision_time` and take the
  latest publication per target. A forecast published one minute after the decision cannot be used.
- Price features read the continuous aggregates (prices_hh / prices_daily / prices_weekly), which are keyed
  on start_time and carry no available_at. They use "Option A": a half-hour bucket is usable only if
  `bucket + 30 min + MID_AVAILABILITY_DELAY_MIN <= decision_time` (bucket start <= decision_time - 40 min
  today), and a day or week only once all of its half-hours are usable. This equals the available_at rule
  ONLY because MID's available_at is always start + 30 min + delay (stamped at ingest), so build_features
  refuses to run if the stored MID offset differs from the configured delay. A leak cannot hide behind an
  edited constant.
- Every point-in-time filter is one SQL line ending in `-- pit`; tests/db/test_pit_leak.py removes each in
  turn and must fail every time.

Conventions:
- decision_time must be timezone-aware. Targets are the next `horizon` half-hours after decision_time
  floored to the half hour (48 half-hours, never "one settlement day": clock-change days have 46 or 50).
- price_lag_1d / price_lag_7d are the price exactly 24 h / 168 h before the target (UTC elapsed time).
- Calendar columns (hour, dow, is_weekend, period_of_day) are UK local time, since demand follows it.
- Missing values never leak through as NaN: lags and aggregates fall back to price_last_known (spreads and
  stddevs to 0) with lag_missing = 1; forecasts forward-fill (WINDFOR is hourly, so 10:30 takes 10:00's
  value; interpolation would need the next hour's forecast, which may not be published yet), then
  back-fill from later targets of the same decision, with fc_missing = 1.
- Every column is float64.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg

FEATURE_COLUMNS = [
    "price_lag_1d",
    "price_lag_7d",
    "price_last_known",
    "hours_since_last_price",
    "daily_spread_lag_1d",
    "weekly_mean",
    "weekly_std",
    "wind_fc",
    "demand_fc",
    "wind_share_fc",
    "hour",
    "dow",
    "is_weekend",
    "period_of_day",
    "lag_missing",
    "fc_missing",
]
REQUIRED_COLUMNS = list(FEATURE_COLUMNS)  # no NaN anywhere: see the fallback rules in the module docstring

HALF_HOUR = timedelta(minutes=30)
LONDON = "Europe/London"
PRICE_SERIES = "APXMIDP"
DEMAND_SERIES = "N"  # NDF publishes the national boundary only


class PointInTimeError(RuntimeError):
    """The data cannot be used without risking lookahead (e.g. MID offset != configured delay)."""


def mid_delay_min() -> int:
    return int(os.environ.get("MID_AVAILABILITY_DELAY_MIN", "10"))


# Each query is one statement. The line ending in "-- pit" is its point-in-time filter.
Q_DELAY_GUARD = """
SELECT DISTINCT extract(epoch FROM available_at - start_time)::int / 60 AS offset_min
FROM grid_raw
WHERE dataset = 'MID' AND series = %(series)s
  AND start_time > %(T)s - interval '8 days' AND start_time <= %(T)s
"""

Q_PRICE_LAGS = """
SELECT bucket, price FROM prices_hh
WHERE bucket = ANY(%(lag_buckets)s)
  AND bucket <= %(cutoff)s  -- pit
"""

Q_PRICE_LAST = """
SELECT bucket, price FROM prices_hh
WHERE bucket >= %(T)s - interval '8 days' AND price IS NOT NULL
  AND bucket <= %(cutoff)s  -- pit
ORDER BY bucket DESC LIMIT 1
"""

Q_DAILY = """
SELECT bucket, spread FROM prices_daily
WHERE bucket >= %(T)s - interval '10 days'
  AND timezone('Europe/London', timezone('Europe/London', bucket) + interval '1 day') <= %(complete)s  -- pit
ORDER BY bucket
"""

Q_WEEKLY = """
SELECT bucket, mean, stddev FROM prices_weekly
WHERE bucket >= %(T)s - interval '21 days'
  AND timezone('Europe/London', timezone('Europe/London', bucket) + interval '7 days') <= %(complete)s  -- pit
ORDER BY bucket DESC LIMIT 1
"""

Q_WIND = """
SELECT DISTINCT ON (start_time) start_time, value FROM grid_raw
WHERE dataset = 'WINDFOR' AND start_time >= %(fc_from)s AND start_time <= %(fc_to)s
  AND available_at <= %(T)s  -- pit
ORDER BY start_time, available_at DESC
"""

Q_DEMAND = """
SELECT DISTINCT ON (start_time) start_time, value FROM grid_raw
WHERE dataset = 'NDF' AND series = %(demand_series)s AND start_time >= %(fc_from)s AND start_time <= %(fc_to)s
  AND available_at <= %(T)s  -- pit
ORDER BY start_time, available_at DESC
"""

QUERIES = {
    "price_lags": Q_PRICE_LAGS,
    "price_last": Q_PRICE_LAST,
    "daily": Q_DAILY,
    "weekly": Q_WEEKLY,
    "wind": Q_WIND,
    "demand": Q_DEMAND,
}


def target_times(decision_time: datetime, horizon: int = 48) -> pd.DatetimeIndex:
    """The next `horizon` half-hour period starts after decision_time (floored to the half hour)."""
    t = pd.Timestamp(decision_time)
    if t.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware (UTC)")
    t0 = t.tz_convert("UTC").floor("30min")
    return pd.DatetimeIndex([t0 + HALF_HOUR * k for k in range(1, horizon + 1)], name="target_time")


def _check_mid_offset(cur: psycopg.Cursor, T: datetime, delay: int) -> None:
    cur.execute(Q_DELAY_GUARD, {"series": PRICE_SERIES, "T": T})
    offsets = {r[0] for r in cur.fetchall()}
    expected = 30 + delay
    if offsets and offsets != {expected}:
        raise PointInTimeError(
            f"MID rows near {T:%Y-%m-%d %H:%M} have available_at - start_time = {sorted(offsets)} min, but "
            f"MID_AVAILABILITY_DELAY_MIN={delay} implies {expected} min. The aggregate cutoff would be wrong "
            "(a leak if the delay was lowered). Reload MID with the new delay or restore the old value."
        )


def build_features(conn: psycopg.Connection, decision_time: datetime, horizon: int = 48) -> pd.DataFrame:
    """Features for the next `horizon` half-hours, using only data available at decision_time.

    Returns a DataFrame indexed by target_time (UTC) with FEATURE_COLUMNS, all float64, no NaN.
    Raises PointInTimeError if the stored MID offset disagrees with MID_AVAILABILITY_DELAY_MIN, and
    ValueError if no price is available in the 8 days before decision_time.
    """
    targets = target_times(decision_time, horizon)
    T = pd.Timestamp(decision_time).tz_convert("UTC").to_pydatetime()
    delay = mid_delay_min()
    cutoff = T - timedelta(minutes=30 + delay)  # latest usable half-hour bucket start
    complete_by = cutoff + HALF_HOUR  # a day/week is usable once it ends by here
    lag_1d = targets - pd.Timedelta(days=1)
    lag_7d = targets - pd.Timedelta(days=7)
    fc_from = (targets[0] - pd.Timedelta(hours=24)).floor("1h")  # 24 h earlier so forward-fill has a start
    fc_to = targets[-1]

    params = {
        "T": T,
        "cutoff": cutoff,
        "complete": complete_by,
        "lag_buckets": [t.to_pydatetime() for t in lag_1d.append(lag_7d)],
        "fc_from": fc_from.to_pydatetime(),
        "fc_to": fc_to.to_pydatetime(),
        "demand_series": DEMAND_SERIES,
    }

    with conn.cursor() as cur:
        _check_mid_offset(cur, T, delay)
    # One round trip for all six queries: Tiger is in us-east-1, the decision runs from London.
    cursors = {name: conn.cursor() for name in QUERIES}
    try:
        with conn.pipeline():
            for name, q in QUERIES.items():
                cursors[name].execute(q, params)
        rows = {name: cur.fetchall() for name, cur in cursors.items()}
    finally:
        for cur in cursors.values():
            cur.close()

    if not rows["price_last"]:
        raise ValueError(f"no APX price available in the 8 days before {T:%Y-%m-%d %H:%M} UTC")
    last_bucket, last_price = rows["price_last"][0]
    last_price = float(last_price)

    out = pd.DataFrame(index=targets)
    lag_missing = np.zeros(len(targets))

    # --- price lags -----------------------------------------------------------------------------
    prices = {pd.Timestamp(b).tz_convert("UTC"): float(p) for b, p in rows["price_lags"] if p is not None}
    for col, lagged in (("price_lag_1d", lag_1d), ("price_lag_7d", lag_7d)):
        vals = np.array([prices.get(t, np.nan) for t in lagged])
        lag_missing = np.maximum(lag_missing, np.isnan(vals))
        out[col] = np.where(np.isnan(vals), last_price, vals)

    out["price_last_known"] = last_price
    period_end = pd.Timestamp(last_bucket).tz_convert("UTC") + HALF_HOUR
    out["hours_since_last_price"] = (pd.Timestamp(T) - period_end).total_seconds() / 3600

    # --- daily spread: the London day before the target's day if complete, else the latest complete day
    daily = {pd.Timestamp(b).tz_convert(LONDON).date(): float(s) for b, s in rows["daily"] if s is not None}
    latest_spread = daily[max(daily)] if daily else np.nan
    prev_days = [(t.tz_convert(LONDON).normalize() - pd.Timedelta(days=1)).date() for t in targets]
    spread = np.array([daily.get(d, latest_spread) for d in prev_days], dtype=float)
    lag_missing = np.maximum(lag_missing, np.isnan(spread))
    out["daily_spread_lag_1d"] = np.where(np.isnan(spread), 0.0, spread)

    # --- weekly regime: latest complete London week ----------------------------------------------
    if rows["weekly"] and rows["weekly"][0][1] is not None:
        _, wmean, wstd = rows["weekly"][0]
        out["weekly_mean"] = float(wmean)
        out["weekly_std"] = float(wstd) if wstd is not None else 0.0
    else:
        out["weekly_mean"] = last_price
        out["weekly_std"] = 0.0
        lag_missing[:] = 1.0

    # --- forecasts: latest publication at or before decision_time ----------------------------------
    fc_missing = np.zeros(len(targets))
    wind = pd.Series({pd.Timestamp(s).tz_convert("UTC"): float(v) for s, v in rows["wind"]}, dtype=float)
    demand = pd.Series({pd.Timestamp(s).tz_convert("UTC"): float(v) for s, v in rows["demand"]}, dtype=float)
    for col, series, step in (("wind_fc", wind, "1h"), ("demand_fc", demand, "30min")):
        keys = targets.floor(step)  # WINDFOR is hourly: 10:30 reads the 10:00 forecast (forward-fill)
        vals = series.reindex(keys).to_numpy(dtype=float)
        if np.isnan(vals).any():
            # Forward-fill from the latest earlier forecast hour, then back-fill from later targets.
            # Every value used was published at or before decision_time, so neither direction leaks.
            fc_missing = np.maximum(fc_missing, np.isnan(vals))
            history = series.sort_index()
            filled = pd.Series(vals, index=targets)
            earlier = history[history.index < keys[0]]
            if len(earlier):
                filled.iloc[0] = earlier.iloc[-1] if np.isnan(filled.iloc[0]) else filled.iloc[0]
            filled = filled.ffill().bfill()
            vals = filled.to_numpy(dtype=float)
        if np.isnan(vals).all():
            raise ValueError(f"no {col} published at or before {T:%Y-%m-%d %H:%M} UTC for the horizon")
        out[col] = vals
    out["wind_share_fc"] = out["wind_fc"] / out["demand_fc"]

    # --- calendar, UK local time ------------------------------------------------------------------
    local = targets.tz_convert(LONDON)
    midnight = local.normalize()
    out["hour"] = local.hour
    out["dow"] = local.day_of_week
    out["is_weekend"] = (local.day_of_week >= 5).astype(float)
    out["period_of_day"] = ((local - midnight) / pd.Timedelta(minutes=30)).astype(int) + 1  # SP, 1..50

    out["lag_missing"] = lag_missing
    out["fc_missing"] = fc_missing
    return out[FEATURE_COLUMNS].astype("float64")
