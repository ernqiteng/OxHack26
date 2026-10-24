"""Known answer (docs/girik.md Phase 2): hourly WINDFOR 100 at 10:00 and 200 at 11:00 gives wind_fc 100 at
10:00 and 10:30 (forward-fill, decided: interpolation would need the 11:00 forecast for 10:30 and that is
not always published yet at decision time), and 200 at 11:00."""

from datetime import timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, refresh_caggs, upsert_grid_raw
from tempo.features.build import build_features
from tests.db.helpers import MONDAY, clean, forecast_frame, mid_frame

DAY = MONDAY + timedelta(days=22)  # Tue 28 Jan 2025 (GMT, so UTC = UK local)


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    upsert_grid_raw(db_conn, mid_frame(MONDAY, 30))
    upsert_grid_raw(db_conn, forecast_frame("NDF", MONDAY, 30, step="30min", series="N"))
    wind = pd.DataFrame(
        {
            "start_time": [DAY + timedelta(hours=10), DAY + timedelta(hours=11)],
            "available_at": DAY + timedelta(hours=8),
            "dataset": "WINDFOR",
            "series": "",
            "value": [100.0, 200.0],
        }
    )
    upsert_grid_raw(db_conn, wind)
    refresh_caggs(db_conn, MONDAY - timedelta(days=7), MONDAY + timedelta(days=44))
    try:
        yield db_conn
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=30))


def test_hourly_wind_is_forward_filled_to_half_hours(conn):
    f = build_features(conn, DAY + timedelta(hours=9, minutes=40))  # first target 10:00
    at = lambda h, m=0: f.loc[pd.Timestamp(DAY + timedelta(hours=h, minutes=m)), "wind_fc"]  # noqa: E731
    assert at(10) == 100.0
    assert at(10, 30) == 100.0  # forward-fill, not 150 (interpolation)
    assert at(11) == 200.0
    assert at(11, 30) == 200.0


def test_exact_hours_are_not_flagged_missing(conn):
    f = build_features(conn, DAY + timedelta(hours=9, minutes=40))
    for h, m in ((10, 0), (10, 30), (11, 0), (11, 30)):
        assert f.loc[pd.Timestamp(DAY + timedelta(hours=h, minutes=m)), "fc_missing"] == 0.0
    # 12:00 has no forecast hour of its own: carried forward from 11:00 and flagged.
    noon = pd.Timestamp(DAY + timedelta(hours=12))
    assert f.loc[noon, "wind_fc"] == 200.0 and f.loc[noon, "fc_missing"] == 1.0


def test_wind_share_uses_the_filled_value(conn):
    f = build_features(conn, DAY + timedelta(hours=9, minutes=40))
    t = pd.Timestamp(DAY + timedelta(hours=10, minutes=30))
    assert f.loc[t, "wind_share_fc"] == pytest.approx(100.0 / f.loc[t, "demand_fc"])
