"""lookahead_check (Gate 1): flags impossible timestamps, not conservative ones.

Found running the live poller: Elexon published MID for the 18:30 period at 18:42, during the period. Our
derived MID stamp (start + 40 min) is then after now() for the in-progress period. That row is not usable
yet (build_features ignores it) and must not be reported as lookahead; a MID price for a period that has
not started, or any publish-time dataset stamped in the future, must be.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, run_sql, upsert_grid_raw
from tempo.ingest.backfill import lookahead_check


def row(dataset, start, available, series=""):
    return pd.DataFrame(
        {"start_time": [pd.Timestamp(start)], "available_at": [pd.Timestamp(available)], "dataset": dataset,
         "series": series, "value": [1.0]}
    )  # fmt: skip


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    yield db_conn
    db_conn.execute("TRUNCATE grid_raw")


def now():
    return datetime.now(UTC).replace(microsecond=0)


def test_in_progress_mid_period_is_not_lookahead(conn):
    start = now() - timedelta(minutes=12)  # period started 12 min ago, stamped available at +40 min
    upsert_grid_raw(conn, row("MID", start, start + timedelta(minutes=40), "APXMIDP"))
    assert run_sql(conn, "SELECT count(*) FROM grid_raw WHERE available_at > now()")[0][0] == 1
    assert lookahead_check(conn) == 0


def test_mid_for_a_period_that_has_not_started_is_lookahead(conn):
    start = now() + timedelta(minutes=30)
    upsert_grid_raw(conn, row("MID", start, start + timedelta(minutes=40), "APXMIDP"))
    assert lookahead_check(conn) == 1


@pytest.mark.parametrize("dataset", ["INDO", "FUELHH", "DISEBSP", "WINDFOR", "NDF"])
def test_publish_time_in_the_future_is_lookahead(conn, dataset):
    upsert_grid_raw(conn, row(dataset, now() - timedelta(hours=1), now() + timedelta(hours=1)))
    assert lookahead_check(conn) == 1


@pytest.mark.parametrize("dataset", ["WINDFOR", "NDF"])
def test_forecast_for_the_future_published_in_the_past_is_fine(conn, dataset):
    upsert_grid_raw(conn, row(dataset, now() + timedelta(hours=6), now() - timedelta(hours=1)))
    assert lookahead_check(conn) == 0
