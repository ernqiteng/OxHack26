"""LightGBM p50 beats persistence on unseen synthetic days: the fixture's wind signal is learnable.

Persistence copies yesterday, so it is wrong every time the week flips between windy and calm (night
prices move by 30) and around weekends (peak moves by 15). wind_fc and dow tell LightGBM both.
"""

import numpy as np
import pytest

from tempo.forecast.lgbm import LightGBMQuantileForecaster
from tempo.forecast.persistence import PersistenceForecaster
from tests.unit.forecast_frames import LGBM_FIXTURE_FEATURES, lgbm_frame

TRAIN_DAYS, TEST_DAYS = 40, 14
DETERMINISTIC = {"random_state": 0, "deterministic": True, "n_jobs": 1}  # seed=0, num_threads=1


@pytest.fixture(scope="module")
def split():
    frame = lgbm_frame(days=8 + TRAIN_DAYS + TEST_DAYS)
    train, test = frame.iloc[: TRAIN_DAYS * 48], frame.iloc[TRAIN_DAYS * 48 :]
    assert len(test) == TEST_DAYS * 48
    return train, test


def mae(pred, actual):
    return float(np.mean(np.abs(pred.to_numpy() - actual.to_numpy())))


def test_lgbm_p50_mae_below_persistence(split):
    train, test = split
    lgbm = LightGBMQuantileForecaster(features=LGBM_FIXTURE_FEATURES, **DETERMINISTIC)
    lgbm.fit(train, train.price)
    pers = PersistenceForecaster()
    pers.fit(train, train.price)
    lgbm_mae, pers_mae = mae(lgbm.predict(test).p50, test.price), mae(pers.predict(test).p50, test.price)
    assert lgbm_mae < pers_mae, f"LightGBM MAE {lgbm_mae:.2f} vs persistence {pers_mae:.2f}"


def test_training_is_deterministic(split):
    train, test = split
    preds = []
    for _ in range(2):
        f = LightGBMQuantileForecaster(features=LGBM_FIXTURE_FEATURES, **DETERMINISTIC)
        f.fit(train, train.price)
        preds.append(f.predict(test).to_numpy())
    assert np.array_equal(preds[0], preds[1])
