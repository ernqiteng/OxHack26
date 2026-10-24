"""PersistenceForecaster on synthetic prices: p50 is yesterday's price, the band covers ~80%."""

import numpy as np
import pandas as pd
import pytest

from tempo.backtest.walkforward import prices_hh_from_grid_raw
from tempo.forecast.persistence import PersistenceForecaster
from tests.fixtures.synthetic import make_synthetic_market
from tests.unit.forecast_frames import persistence_frame


@pytest.fixture(scope="module")
def frame():
    return persistence_frame(days=60)


def test_p50_is_price_one_day_before(frame):
    f = PersistenceForecaster()
    f.fit(frame.iloc[: 30 * 48], frame.price.iloc[: 30 * 48])
    out = f.predict(frame)
    prices = prices_hh_from_grid_raw(make_synthetic_market(days=60)).set_index("bucket").price
    yesterday = prices.reindex(frame.index - pd.Timedelta(days=1)).to_numpy()
    assert out.p50.to_numpy() == pytest.approx(yesterday)  # exact copy, every row
    assert out.index.equals(frame.index)


def test_band_covers_80_pct_on_train(frame):
    train = frame.iloc[: 30 * 48]
    f = PersistenceForecaster()
    f.fit(train, train.price)
    out = f.predict(train)
    inside = (train.price >= out.p10) & (train.price <= out.p90)
    assert inside.mean() == pytest.approx(0.8, abs=0.01)


def test_band_ordered_and_k_positive(frame):
    f = PersistenceForecaster()
    f.fit(frame, frame.price)
    out = f.predict(frame)
    assert f.k > 0
    assert (out.p10 <= out.p50).all() and (out.p50 <= out.p90).all()


def test_flat_week_does_not_divide_by_zero():
    idx = pd.date_range("2026-01-05", periods=10, freq="30min", tz="UTC")
    X = pd.DataFrame({"price_lag_1d": 50.0, "weekly_std": 0.0}, index=idx)
    f = PersistenceForecaster()
    f.fit(X, pd.Series(50.0, index=idx))
    assert np.isfinite(f.predict(X).to_numpy()).all()


def test_predict_before_fit_fails():
    with pytest.raises(RuntimeError):
        PersistenceForecaster().predict(persistence_frame(days=9))
