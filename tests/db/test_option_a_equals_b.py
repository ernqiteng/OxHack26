"""Option A (build_features' aggregate cutoff) equals Option B (an actual available_at join), on real MID.

build_features reads the price aggregates with a cutoff derived from MID_AVAILABILITY_DELAY_MIN ("Option A").
That is only correct because MID's available_at is stamped as start + 30 + delay at ingest. This test
recomputes every price feature independently from grid_raw with `available_at <= decision_time`
("Option B", completeness of days and weeks taken from the offsets stored in the data, never from the
constant) over 6 weeks of real APX prices across the 26 Oct 2025 clock change, and requires equality.

It must fail if the delay constant drifts from how MID was loaded: the guard in build_features refuses to
run on a mismatch (test_delay_mismatch_refuses), and with the guard bypassed Option A diverges from Option B
(test_constant_drift_without_guard_leaks), so the equivalence would catch it either way.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, run_sql, upsert_grid_raw
from tempo.features import build as fb
from tempo.features.build import PointInTimeError, build_features
from tempo.ingest.elexon import normalise
from tests.db.helpers import clean, forecast_frame

SAMPLE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "elexon_samples" / "MID_APX_2025-10-01_2025-11-12.json"
)
LOADED_DELAY = 10  # the MID delay the data is stamped with here, on local Docker and on Tiger
START = datetime(2025, 10, 1, tzinfo=UTC)
END = datetime(2025, 11, 12, tzinfo=UTC)
# Every 5 h 17 min from 15 Oct (two complete London weeks behind it) to 10 Nov: 121 decision times,
# every minute-of-hour and hour-of-day mix, across the clock change on Sun 26 Oct 2025.
DECISIONS = list(pd.date_range("2025-10-15 00:10", "2025-11-10 00:00", freq="317min", tz="UTC"))
PRICE_COLS = [
    "price_lag_1d",
    "price_lag_7d",
    "price_last_known",
    "hours_since_last_price",
    "daily_spread_lag_1d",
    "weekly_mean",
    "weekly_std",
    "lag_missing",
]


@pytest.fixture(scope="module")
def conn():
    import os

    import psycopg

    url = os.environ.get("TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres")
    try:
        c = psycopg.connect(url, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local test DB not reachable ({exc}); run scripts/dev_db.sh")
    apply_schema(c)
    rows = json.loads(SAMPLE.read_text(encoding="utf-8"))
    upsert_grid_raw(c, normalise("MID", rows, mid_delay=LOADED_DELAY))
    # Forecasts only so build_features can run; they do not touch the price columns compared here.
    upsert_grid_raw(c, forecast_frame("WINDFOR", START, 42, step="1h"))
    upsert_grid_raw(c, forecast_frame("NDF", START, 42, step="30min", series="N"))
    refresh_caggs(c, START - timedelta(days=7), END + timedelta(days=14))
    try:
        yield c
    finally:
        clean(c, START, END)
        c.close()


def option_b(conn, decision_time: pd.Timestamp, targets: pd.DatetimeIndex) -> pd.DataFrame:
    """Price features from grid_raw with available_at <= T. Day/week completeness uses the offset stored in
    the data (available_at - start_time of MID rows), not MID_AVAILABILITY_DELAY_MIN."""
    T = decision_time.to_pydatetime()
    raw = pd.DataFrame(
        run_sql(
            conn,
            "SELECT start_time, available_at, value FROM grid_raw "
            "WHERE dataset = 'MID' AND series = 'APXMIDP' AND start_time >= %s",
            (T - timedelta(days=30),),
        ),
        columns=["start_time", "available_at", "value"],
    )
    raw["start_time"] = pd.to_datetime(raw["start_time"], utc=True)
    raw["available_at"] = pd.to_datetime(raw["available_at"], utc=True)
    (offset,) = (raw["available_at"] - raw["start_time"]).unique()  # one offset for all MID rows
    known = raw[raw["available_at"] <= T].set_index("start_time")["value"].sort_index()
    known = known[known.index >= T - timedelta(days=8)].combine_first(known)  # lags may look back 7 days

    last_start = known.index.max()
    last = float(known[last_start])
    out = pd.DataFrame(index=targets)
    missing = np.zeros(len(targets))
    for col, lag in (("price_lag_1d", timedelta(days=1)), ("price_lag_7d", timedelta(days=7))):
        vals = np.array([known.get(t - lag, np.nan) for t in targets], dtype=float)
        missing = np.maximum(missing, np.isnan(vals))
        out[col] = np.where(np.isnan(vals), last, vals)
    out["price_last_known"] = last
    out["hours_since_last_price"] = (
        decision_time - (last_start + pd.Timedelta(minutes=30))
    ).total_seconds() / 3600

    # A London day / week is complete once its final half-hour period is available under the data's offset.
    london = known.index.tz_convert("Europe/London")
    days = pd.Series(known.to_numpy(), index=london.normalize())
    complete_day = {
        d.date(): float(g.max() - g.min())
        for d, g in days.groupby(level=0)
        if (d + pd.Timedelta(days=1) - pd.Timedelta(minutes=30) + offset) <= decision_time
        and d >= decision_time - pd.Timedelta(days=10)
    }
    latest = complete_day[max(complete_day)] if complete_day else np.nan
    spread = np.array(
        [complete_day.get((t.tz_convert("Europe/London").normalize() - pd.Timedelta(days=1)).date(), latest)
         for t in targets], dtype=float,
    )  # fmt: skip
    missing = np.maximum(missing, np.isnan(spread))
    out["daily_spread_lag_1d"] = np.where(np.isnan(spread), 0.0, spread)

    week_start = (london.normalize() - pd.to_timedelta(london.day_of_week, unit="D")).normalize()
    weeks = pd.Series(known.to_numpy(), index=week_start)
    complete_weeks = [
        (w, g)
        for w, g in weeks.groupby(level=0)
        if (w + pd.Timedelta(days=7) - pd.Timedelta(minutes=30) + offset) <= decision_time
        and w >= decision_time - pd.Timedelta(days=21)
    ]
    if complete_weeks:
        _, g = max(complete_weeks, key=lambda wg: wg[0])
        out["weekly_mean"], out["weekly_std"] = float(g.mean()), float(g.std(ddof=1))
    else:
        out["weekly_mean"], out["weekly_std"] = last, 0.0
        missing[:] = 1.0
    out["lag_missing"] = missing
    return out[PRICE_COLS]


def test_fixture_spans_the_clock_change(conn):
    (n,) = run_sql(conn, "SELECT n FROM prices_daily WHERE bucket = '2025-10-25 23:00+00'")[0]
    assert n == 50  # Sun 26 Oct 2025, clocks back
    assert DECISIONS[0] < pd.Timestamp("2025-10-26", tz="UTC") < DECISIONS[-1]
    assert len(DECISIONS) >= 100


def test_option_a_equals_option_b(conn, monkeypatch):
    monkeypatch.setenv("MID_AVAILABILITY_DELAY_MIN", str(LOADED_DELAY))
    mismatches = []
    for T in DECISIONS:
        a = build_features(conn, T)[PRICE_COLS]
        b = option_b(conn, T, a.index)
        for col in PRICE_COLS:
            if not np.allclose(a[col].to_numpy(), b[col].to_numpy(), rtol=1e-9, atol=1e-6):
                mismatches.append((T, col, a[col].to_numpy()[:3], b[col].to_numpy()[:3]))
    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[:3]}"


@pytest.mark.parametrize("configured", [0, 5, 9, 11, 20])
def test_delay_mismatch_refuses(conn, monkeypatch, configured):
    """MID was loaded with delay 10. Any other configured delay must stop build_features, not silently
    shift the aggregate cutoff (lowering it would use prices before they were published)."""
    monkeypatch.setenv("MID_AVAILABILITY_DELAY_MIN", str(configured))
    with pytest.raises(PointInTimeError, match="MID_AVAILABILITY_DELAY_MIN"):
        build_features(conn, DECISIONS[40])


def test_constant_drift_without_guard_leaks(conn, monkeypatch):
    """Why the guard exists: bypass it, lower the constant to 5, and Option A uses a price that Option B
    (the real available_at join) says was not yet published. The equivalence test would then fail."""
    monkeypatch.setenv("MID_AVAILABILITY_DELAY_MIN", "5")
    monkeypatch.setattr(fb, "_check_mid_offset", lambda *a, **k: None)
    leaks = 0
    for T in DECISIONS:
        a = build_features(conn, T)[PRICE_COLS]
        b = option_b(conn, T, a.index)
        if not np.allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-6):
            leaks += 1
    assert leaks > 0


def test_configured_delay_matches_how_data_was_loaded():
    """MID available_at is stamped at ingest, so changing the delay means reloading MID on Tiger.
    Pin both places the value lives; build_features' guard catches it at runtime against real data too."""
    env_example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "MID_AVAILABILITY_DELAY_MIN=10" in env_example
    import os

    saved = os.environ.pop("MID_AVAILABILITY_DELAY_MIN", None)
    try:
        assert fb.mid_delay_min() == LOADED_DELAY  # the code default
    finally:
        if saved is not None:
            os.environ["MID_AVAILABILITY_DELAY_MIN"] = saved
