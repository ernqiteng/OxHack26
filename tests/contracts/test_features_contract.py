"""build_features contract (docs/plan.md 2.2, docs/girik.md Phase 2). Ernqi's run_decision and
make_training_set depend on exactly this shape. Needs the local Docker DB (scripts/dev_db.sh)."""

from datetime import timedelta

import pandas as pd
import pytest

from tempo.db.conn import apply_schema
from tempo.features.build import FEATURE_COLUMNS, REQUIRED_COLUMNS, build_features
from tests.db.helpers import MONDAY, clean, market

DAYS = 30
T = MONDAY + timedelta(days=23, hours=12, minutes=10)  # a Wednesday, mid-period (not on a boundary)

EXPECTED_COLUMNS = [
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


@pytest.fixture(scope="module")
def features(request):
    """One synthetic month loaded once for the module; the DB is cleaned afterwards."""
    db_conn = request.getfixturevalue("db_conn_module")
    apply_schema(db_conn)
    market(db_conn, MONDAY, DAYS)
    try:
        yield db_conn, build_features(db_conn, T)
    finally:
        clean(db_conn, MONDAY, MONDAY + timedelta(days=DAYS))


@pytest.fixture(scope="module")
def db_conn_module():
    import os

    psycopg = pytest.importorskip("psycopg")
    url = os.environ.get("TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres")
    try:
        conn = psycopg.connect(url, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local test DB not reachable ({exc}); run scripts/dev_db.sh")
    yield conn
    conn.close()


def test_columns_are_exactly_the_contract(features):
    _, f = features
    assert list(f.columns) == EXPECTED_COLUMNS == FEATURE_COLUMNS


def test_index_is_48_half_hours_after_the_decision(features):
    _, f = features
    assert f.index.name == "target_time"
    assert len(f) == 48
    assert str(f.index.tz) == "UTC"
    assert f.index[0] == pd.Timestamp(T).floor("30min") + pd.Timedelta(minutes=30)  # 12:30 for T = 12:10
    assert (f.index.to_series().diff().dropna() == pd.Timedelta(minutes=30)).all()


def test_all_columns_float64(features):
    _, f = features
    assert (f.dtypes == "float64").all(), f.dtypes[f.dtypes != "float64"]


def test_no_nan_in_required_columns(features):
    _, f = features
    assert not f[REQUIRED_COLUMNS].isna().any().any(), f[REQUIRED_COLUMNS].isna().sum()


def test_flags_are_zero_or_one(features):
    _, f = features
    for col in ("lag_missing", "fc_missing", "is_weekend"):
        assert set(f[col].unique()) <= {0.0, 1.0}, col


def test_horizon_and_decision_on_a_boundary(features):
    conn, _ = features
    f = build_features(conn, MONDAY + timedelta(days=23, hours=12), horizon=10)  # exactly 12:00
    assert len(f) == 10
    assert f.index[0] == pd.Timestamp(MONDAY + timedelta(days=23, hours=12, minutes=30))


def test_naive_decision_time_is_refused(features):
    conn, _ = features
    with pytest.raises(ValueError, match="timezone-aware"):
        build_features(conn, T.replace(tzinfo=None))


def test_period_of_day_is_uk_settlement_period(features):
    """Synthetic month is in winter (GMT), so period_of_day = half-hours since UTC midnight + 1."""
    _, f = features
    expected = (f.index.hour * 2 + f.index.minute // 30 + 1).astype(float)
    assert (f["period_of_day"].to_numpy() == expected.to_numpy()).all()
