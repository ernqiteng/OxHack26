"""Shared point-in-time contract (docs/plan.md 4.2 rule 2): a row that becomes available after the
decision time must change nothing; a row available before it must change something.

`assert_point_in_time(conn, compute, decision_time)` is the reusable check: `compute(conn, T)` returns any
DataFrame built "as of T" (Girik's build_features, Ernqi's training-set builder, ...). It inserts one
future-available row per dataset (MID, WINDFOR, NDF), asserts the frame is unchanged, then inserts rows
available just before T and asserts the frame changed. The per-column version for build_features is
tests/db/test_pit_leak.py.
"""

from datetime import timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, upsert_grid_raw
from tempo.features.build import build_features
from tests.db.helpers import MONDAY, clean, market

DAYS = 30
T = MONDAY + timedelta(days=23, hours=12, minutes=10)


def _rows(start, available, value, dataset, series):
    return pd.DataFrame(
        {"start_time": [pd.Timestamp(start)], "available_at": [pd.Timestamp(available)], "dataset": dataset,
         "series": series, "value": [value]}
    )  # fmt: skip


def assert_point_in_time(conn, compute, decision_time, delay_min: int = 10):
    t0 = pd.Timestamp(decision_time).floor("30min")
    window = (
        pd.Timestamp(decision_time) - pd.Timedelta(days=40),
        pd.Timestamp(decision_time) + pd.Timedelta(days=10),
    )
    before = compute(conn, decision_time)

    # Available after T: MID for the current period (+40 min > T); forecasts published at T + 1 min.
    upsert_grid_raw(conn, _rows(t0, t0 + pd.Timedelta(minutes=30 + delay_min), 9999.0, "MID", "APXMIDP"))
    for ds, series in (("WINDFOR", ""), ("NDF", "N")):
        upsert_grid_raw(
            conn, _rows(t0 + pd.Timedelta(hours=1), decision_time + timedelta(minutes=1), 99999.0, ds, series)
        )
    refresh_caggs(conn, *window)
    after_future = compute(conn, decision_time)
    pd.testing.assert_frame_equal(before, after_future, check_exact=True)

    # Available before T: the same targets, published at T - 1 min.
    for ds, series in (("WINDFOR", ""), ("NDF", "N")):
        upsert_grid_raw(
            conn, _rows(t0 + pd.Timedelta(hours=1), decision_time - timedelta(minutes=1), 12345.0, ds, series)
        )
    refresh_caggs(conn, *window)
    after_past = compute(conn, decision_time)
    assert not after_past.equals(after_future), (
        "rows available before T changed nothing: the check is vacuous"
    )


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    market(db_conn, MONDAY, DAYS, mid_until=T - timedelta(hours=2))
    try:
        yield db_conn
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=DAYS))


def test_build_features_is_point_in_time(conn):
    assert_point_in_time(conn, build_features, T)
