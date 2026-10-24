"""The training set is built only through build_features(decision_time): every feature value in X equals
what build_features returns for that decision time, horizon_k follows the shared definition, y is the
realised price, and data that arrives after a decision time cannot change its rows."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from tempo.db.conn import upsert_grid_raw
from tempo.features.build import FEATURE_COLUMNS, build_features
from tempo.forecast.dataset import TRAINING_COLUMNS, decision_times, make_training_set
from tests.db.helpers import MONDAY, clean, market

DAYS = 30
START = MONDAY + timedelta(days=9)  # 8 days of history plus a margin
END = MONDAY + timedelta(days=26)


@pytest.fixture
def synthetic_month(db_conn):
    market(db_conn, MONDAY, DAYS)
    yield db_conn
    clean(db_conn, MONDAY, MONDAY + timedelta(days=DAYS))


def test_every_row_equals_build_features(synthetic_month):
    conn = synthetic_month
    times = decision_times(START, END, timedelta(hours=6))
    X, y = make_training_set(conn, times)

    assert list(X.columns) == TRAINING_COLUMNS
    assert len(X) == 48 * len(times) and len(y) == len(X)
    assert X.index.names == ["decision_time", "target_time"]
    assert not X.isna().any().any()

    for dt in times:
        rows = X.xs(pd.Timestamp(dt), level="decision_time")
        expected = build_features(conn, dt)
        pd.testing.assert_frame_equal(rows[FEATURE_COLUMNS], expected, check_names=False)
        t0 = pd.Timestamp(dt).floor("30min")
        k = ((rows.index - t0) / pd.Timedelta(minutes=30)).astype(int)
        assert list(k) == list(range(1, 49))
        assert rows["horizon_k"].tolist() == [float(i) for i in range(1, 49)]


def test_y_is_the_realised_price_and_nan_before_settlement(synthetic_month):
    conn = synthetic_month
    last_price_time = conn.execute("SELECT max(bucket) FROM prices_hh").fetchone()[0]
    # a decision 12 h before the end of the data: half the horizon is settled, half is not
    dt = last_price_time - timedelta(hours=12)
    X, y = make_training_set(conn, [dt])
    settled = y.notna()
    assert 20 <= settled.sum() <= 26
    targets = X.index.get_level_values("target_time")
    prices = dict(conn.execute("SELECT bucket, price FROM prices_hh WHERE bucket > %s", (dt,)).fetchall())
    for t, v in zip(targets[settled], y[settled], strict=True):
        assert v == pytest.approx(prices[t.to_pydatetime()])


def test_rows_do_not_change_when_future_data_arrives(synthetic_month):
    conn = synthetic_month
    dt = START + timedelta(days=3, hours=12)
    X1, y1 = make_training_set(conn, [dt])
    # a price "from the future" for the first target, visible only after dt (available_at > dt)
    first_target = X1.index.get_level_values("target_time")[0]
    upsert_grid_raw(
        conn,
        pd.DataFrame(
            {
                "start_time": [first_target],
                "available_at": [pd.Timestamp(dt) + pd.Timedelta(minutes=5)],
                "dataset": "MID",
                "series": "APXMIDP",
                "value": [9999.0],
            }
        ),
    )
    X2, _ = make_training_set(conn, [dt])
    pd.testing.assert_frame_equal(X1, X2)


def test_strict_false_skips_unusable_times_and_strict_raises(synthetic_month):
    conn = synthetic_month
    too_early = MONDAY - timedelta(days=1)  # before any price exists: build_features refuses it
    with pytest.raises(ValueError):
        make_training_set(conn, [too_early, START])
    X, _ = make_training_set(conn, [too_early, START], strict=False)
    assert X.index.get_level_values("decision_time").unique().tolist() == [pd.Timestamp(START)]
    with pytest.raises(ValueError, match="every one of"):
        make_training_set(conn, [too_early], strict=False)


def test_lightgbm_fits_on_the_training_set(synthetic_month):
    from tempo.forecast.lgbm import LightGBMQuantileForecaster

    conn = synthetic_month
    X, y = make_training_set(conn, decision_times(START, END, timedelta(hours=12)))
    model = LightGBMQuantileForecaster(n_estimators=30)
    model.fit(X, y)
    pred = model.predict(X.iloc[:48])
    assert list(pred.columns) == ["p10", "p50", "p90"] and len(pred) == 48
    assert (pred.p10 <= pred.p50).all() and (pred.p50 <= pred.p90).all()
    assert np.isfinite(pred.to_numpy()).all()
