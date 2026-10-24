"""scripts/train.py trains on a synthetic month, saves three joblib files plus training.json, and the
saved model loads and predicts ordered quantiles."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tempo.forecast.lgbm import LightGBMQuantileForecaster
from tests.db.helpers import MONDAY, clean, market

DAYS = 30


@pytest.fixture
def synthetic_month(db_conn):
    market(db_conn, MONDAY, DAYS)
    yield db_conn
    clean(db_conn, MONDAY, MONDAY + timedelta(days=DAYS))


def test_train_saves_a_loadable_model(synthetic_month, tmp_path):
    import scripts.train as train_script

    meta = train_script.train(
        synthetic_month, days=12, every_h=12, out=tmp_path, holdout_days=3, n_estimators=40
    )

    files = sorted(p.name for p in Path(tmp_path).iterdir())
    assert files == ["lgbm_p10.joblib", "lgbm_p50.joblib", "lgbm_p90.joblib", "training.json"]
    assert meta["rows"] == 48 * meta["decision_times"] and meta["rows_with_price"] > 0
    assert meta["holdout"] is not None and 0.0 <= meta["holdout"]["band_coverage"] <= 1.0
    assert json.loads((tmp_path / "training.json").read_text())["features"][-1] == "horizon_k"

    model = LightGBMQuantileForecaster.load(tmp_path)
    from tempo.forecast.dataset import make_training_set

    X, _ = make_training_set(synthetic_month, [MONDAY + timedelta(days=20, hours=6)])
    pred = model.predict(X)
    assert len(pred) == 48 and (pred.p10 <= pred.p50).all() and (pred.p50 <= pred.p90).all()


def test_train_cli_local(synthetic_month, tmp_path, monkeypatch):
    import scripts.train as train_script

    rc = train_script.main(
        ["--db", "local", "--days", "10", "--every", "12", "--holdout-days", "2", "--out", str(tmp_path)]
    )
    assert rc == 0 and (tmp_path / "lgbm_p50.joblib").exists()


def test_until_trains_only_on_prices_published_by_then(synthetic_month, tmp_path):
    """--until: the last training target's price (start + 30 min + MID delay) is published by `until`, so a
    model trained this way can make decisions dated from `until` on without having seen their outcomes."""
    import pandas as pd

    import scripts.train as train_script

    until = pd.Timestamp(MONDAY + timedelta(days=20, hours=18))
    meta = train_script.train(
        synthetic_month, days=10, every_h=6, out=tmp_path, holdout_days=2, until=until, n_estimators=20
    )
    last_decision = pd.Timestamp(meta["window"][-1])
    last_target_published = last_decision.floor("30min") + pd.Timedelta(hours=24, minutes=40)
    assert last_target_published <= until
    assert last_target_published > until - pd.Timedelta(hours=6)  # as late as the 6 h grid allows
    assert meta["until"] == str(until.tz_convert("UTC"))
