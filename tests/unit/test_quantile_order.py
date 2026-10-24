"""LightGBMQuantileForecaster: p10 <= p50 <= p90 on every row, whatever the input."""

import numpy as np
import pandas as pd
import pytest

from tempo.forecast.lgbm import FEATURES, LightGBMQuantileForecaster
from tests.unit.forecast_frames import LGBM_FIXTURE_FEATURES, lgbm_frame

SMALL = {"n_estimators": 50}  # ordering does not depend on model quality; keep the fit fast


@pytest.fixture(scope="module")
def model():
    frame = lgbm_frame()
    f = LightGBMQuantileForecaster(features=LGBM_FIXTURE_FEATURES, **SMALL)
    f.fit(frame, frame.price)
    return f


@pytest.mark.parametrize("seed", range(5))
def test_sorted_on_random_inputs(model, seed):
    rng = np.random.default_rng(seed)
    n = 2000
    X = pd.DataFrame(rng.normal(0, 1, (n, len(LGBM_FIXTURE_FEATURES))) * 1e4, columns=LGBM_FIXTURE_FEATURES)
    X["is_weekend"] = rng.random(n) < 0.3
    out = model.predict(X)
    assert list(out.columns) == ["p10", "p50", "p90"]
    assert out.index.equals(X.index)
    assert np.isfinite(out.to_numpy()).all()
    assert (out.p10 <= out.p50).all() and (out.p50 <= out.p90).all()


class _Const:
    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value)


def test_crossed_quantiles_are_sorted_not_changed():
    """Independent quantile models can cross; predict() reorders each row and changes no value."""
    f = LightGBMQuantileForecaster(features=["x"])
    f.models = {"p10": _Const(9.0), "p50": _Const(1.0), "p90": _Const(5.0)}
    out = f.predict(pd.DataFrame({"x": [0.0, 1.0]}))
    assert out.to_numpy().tolist() == [[1.0, 5.0, 9.0], [1.0, 5.0, 9.0]]


def test_default_features_are_build_features_plus_horizon():
    assert FEATURES[-1] == "horizon_k"
    assert "price_lag_1d" in FEATURES and "wind_share_fc" in FEATURES


def test_missing_feature_column_fails(model):
    with pytest.raises(KeyError, match="wind_fc"):
        model.predict(lgbm_frame().drop(columns="wind_fc"))


def test_predict_before_fit_fails():
    with pytest.raises(RuntimeError):
        LightGBMQuantileForecaster().predict(pd.DataFrame())


def test_save_load_round_trip(model, tmp_path):
    paths = model.save(tmp_path)
    assert sorted(p.name for p in paths) == ["lgbm_p10.joblib", "lgbm_p50.joblib", "lgbm_p90.joblib"]
    loaded = LightGBMQuantileForecaster.load(tmp_path)
    assert loaded.features == LGBM_FIXTURE_FEATURES
    X = lgbm_frame().iloc[:200]
    pd.testing.assert_frame_equal(loaded.predict(X), model.predict(X))
