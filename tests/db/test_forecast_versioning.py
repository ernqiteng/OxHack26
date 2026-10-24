"""Known answer (docs/girik.md Phase 2): two WINDFOR publications for the same target hour, 06:00 saying
500 and 08:00 saying 700. A 07:00 decision gets 500, a 09:00 decision gets 700. The same rule for NDF.
A decision at exactly 08:00 already sees the 08:00 publication (available_at <= decision_time)."""

from datetime import timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, upsert_grid_raw
from tempo.features.build import build_features
from tests.db.helpers import MONDAY, clean, forecast_frame, mid_frame

DAY = MONDAY + timedelta(days=22)  # Tue 28 Jan 2025
TARGET = DAY + timedelta(hours=10)  # in the horizon of every decision below


def publications(dataset, series, step, first, second):
    starts = pd.date_range(TARGET, TARGET + pd.Timedelta(hours=1), freq=step, inclusive="left", tz="UTC")
    return pd.concat(
        [
            pd.DataFrame({"start_time": starts, "available_at": DAY + timedelta(hours=6), "dataset": dataset,
                          "series": series, "value": first}),
            pd.DataFrame({"start_time": starts, "available_at": DAY + timedelta(hours=8), "dataset": dataset,
                          "series": series, "value": second}),
        ],
        ignore_index=True,
    )  # fmt: skip


@pytest.fixture(params=["WINDFOR", "NDF"])
def case(request, db_conn):
    """Load MID plus the OTHER forecast as background, and only the two publications for the one tested."""
    dataset = request.param
    apply_schema(db_conn)
    upsert_grid_raw(db_conn, mid_frame(MONDAY, 30))
    if dataset == "WINDFOR":
        upsert_grid_raw(db_conn, forecast_frame("NDF", MONDAY, 30, step="30min", series="N"))
        upsert_grid_raw(db_conn, publications("WINDFOR", "", "1h", 500.0, 700.0))
        col = "wind_fc"
    else:
        upsert_grid_raw(db_conn, forecast_frame("WINDFOR", MONDAY, 30, step="1h"))
        upsert_grid_raw(db_conn, publications("NDF", "N", "30min", 500.0, 700.0))
        col = "demand_fc"
    refresh_caggs(db_conn, MONDAY - timedelta(days=7), MONDAY + timedelta(days=44))
    try:
        yield db_conn, col
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=30))


def value_at_target(conn, col, decision_hour, minute=0):
    f = build_features(conn, DAY + timedelta(hours=decision_hour, minutes=minute))
    return f.loc[pd.Timestamp(TARGET), col]


def test_0700_decision_uses_the_0600_publication(case):
    conn, col = case
    assert value_at_target(conn, col, 7) == 500.0


def test_0900_decision_uses_the_0800_publication(case):
    conn, col = case
    assert value_at_target(conn, col, 9) == 700.0


def test_decision_exactly_at_0800_sees_the_0800_publication(case):
    conn, col = case
    assert value_at_target(conn, col, 8) == 700.0


def test_0759_decision_still_uses_the_0600_publication(case):
    conn, col = case
    assert value_at_target(conn, col, 7, 59) == 500.0
