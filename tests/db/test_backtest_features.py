"""FrameConn answers build_features' queries exactly as the database does (docs/b.md item 2).

Loads Girik's synthetic market into the local DB, then for many decision times compares
build_features(real connection) with build_features(FrameConn(load_frames(real connection))). Covers the
cases where build_features' fallbacks kick in: no 7-day history yet, MID stopping before the decision,
decision times on and between half-hour boundaries, a London week boundary, and the March clock change.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tempo.backtest.features import features_at, load_frames
from tempo.db.conn import apply_schema
from tempo.features.build import FEATURE_COLUMNS, build_features
from tests.db.helpers import MONDAY, clean, market

DAYS = 30
SPRING = datetime(2025, 3, 17, tzinfo=UTC)  # Monday; clocks go forward Sun 30 Mar 2025, 01:00 UTC
MID_STOP = MONDAY + timedelta(days=20, hours=9)


def _decision_times(start):
    offsets = [
        timedelta(days=2, hours=6),  # under 7 days of history: price_lag_7d falls back
        timedelta(days=9, hours=12),  # on a half-hour boundary
        timedelta(days=9, hours=12, minutes=10),  # mid-period
        timedelta(days=14, minutes=5),  # just after a London week ends (Monday 00:00)
        timedelta(days=17, hours=23, minutes=59),
        timedelta(days=21, hours=3, minutes=40),  # after MID_STOP in the January market
        timedelta(days=25, hours=17, minutes=29),
    ]
    return [start + o for o in offsets]


CASES = [
    ("january, MID stops early", MONDAY, MID_STOP, _decision_times(MONDAY)),
    (
        "spring clock change",
        SPRING,
        None,
        _decision_times(SPRING)
        + [datetime(2025, 3, 30, 0, 50, tzinfo=UTC), datetime(2025, 3, 30, 23, 5, tzinfo=UTC)],
    ),
]


@pytest.fixture(scope="module", params=CASES, ids=[c[0] for c in CASES])
def loaded(request):
    import os

    import psycopg

    url = os.environ.get("TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres")
    try:
        conn = psycopg.connect(url, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local test DB not reachable ({exc}); run scripts/dev_db.sh")
    _, start, mid_until, times = request.param
    apply_schema(conn)
    try:
        market(conn, start, DAYS, mid_until=mid_until)
        yield conn, load_frames(conn), times, mid_until
    finally:
        clean(conn, start, start + timedelta(days=DAYS))
        conn.close()


def test_frames_give_the_same_features_as_the_database(loaded):
    conn, frames, times, _ = loaded
    for T in times:
        db = build_features(conn, T)
        mem = features_at(frames, T)
        assert mem.columns.tolist() == FEATURE_COLUMNS + ["horizon_k"]
        pd.testing.assert_frame_equal(
            mem[FEATURE_COLUMNS], db, check_exact=False, rtol=1e-9, atol=1e-6, obj=f"T={T}"
        )


def test_the_cases_exercise_the_fallbacks(loaded):
    """Guard against a vacuous comparison: some decision times must hit the lag fallback, and where MID stops
    early, some must see a stale last price."""
    _, frames, times, mid_until = loaded
    feats = [features_at(frames, T) for T in times]
    assert any(f.lag_missing.any() for f in feats)
    if mid_until is not None:
        assert any(f.hours_since_last_price.iloc[0] > 12 for f in feats)


def test_horizon_k_counts_half_hours_ahead(loaded):
    _, frames, times, _ = loaded
    f = features_at(frames, times[1])
    assert f.horizon_k.tolist() == list(np.arange(1.0, 49.0))
    assert (f.index - pd.Timestamp(times[1])).max() == pd.Timedelta(hours=24)


def test_no_forecasts_raise_the_same_valueerror(db_conn):
    """With prices but no WINDFOR / NDF at all, build_features raised TypeError (empty Series with a
    non-datetime index); both the database and FrameConn must now raise its 'no ... published' ValueError."""
    from tempo.db.conn import refresh_caggs, upsert_grid_raw
    from tests.db.helpers import mid_frame

    apply_schema(db_conn)
    try:
        upsert_grid_raw(db_conn, mid_frame(MONDAY, 14))
        refresh_caggs(db_conn, MONDAY - timedelta(days=7), MONDAY + timedelta(days=28))
        T = MONDAY + timedelta(days=10)
        with pytest.raises(ValueError, match="no wind_fc published"):
            build_features(db_conn, T)
        with pytest.raises(ValueError, match="no wind_fc published"):
            features_at(load_frames(db_conn), T)
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=14))
