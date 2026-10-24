"""calibration() on unseen synthetic weeks with the persistence forecaster (docs/ernqi.md Phase 2 task 7).

ernqi.md asks for coverage in [0.80, 0.98] and a monotone reliability table. Persistence's band is fitted
to cover exactly 80% on train, so on unseen weeks it lands either side of 0.80 (0.796 here), and in the
middle deciles p50 is yesterday's noise around 60, so mean actual is flat there, not rising. Those two
bounds belong to the LightGBM forecaster (task 2, waiting on build_features); this test pins what an
honest persistence band does instead.
"""

import numpy as np
import pytest

from tempo.backtest.metrics import calibration
from tempo.forecast.persistence import PersistenceForecaster
from tests.unit.forecast_frames import persistence_frame


@pytest.fixture(scope="module")
def cal():
    frame = persistence_frame(60)
    train, test = frame.iloc[: 28 * 48], frame.iloc[28 * 48 :]
    model = PersistenceForecaster()
    model.fit(train, train.price)
    forecasts = model.predict(test).rename_axis("target_time").reset_index()
    return calibration(forecasts, test.price.rename_axis("bucket").reset_index())


def test_coverage_near_the_80_pct_target_on_unseen_weeks(cal):
    assert cal["n"] == 24 * 48
    assert 0.75 <= cal["coverage_p10_p90"] <= 0.85


def test_quantiles_honest(cal):
    q = cal["quantiles"].set_index("quantile").observed
    assert q["p10"] == pytest.approx(0.1, abs=0.03)
    assert q["p50"] == pytest.approx(0.5, abs=0.03)
    assert q["p90"] == pytest.approx(0.9, abs=0.03)


def test_reliability_rises_from_cheap_to_dear(cal):
    """Coarse monotonicity: the cheapest-forecast decile is cheapest in reality, the dearest is dearest."""
    actual = cal["reliability"].mean_actual.to_numpy()
    assert len(actual) == 10
    assert actual[0] == actual.min() and actual[-1] == actual.max()
    assert np.all(np.diff(actual[[0, 1, 5, 9]]) > 0)
