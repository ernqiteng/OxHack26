"""tempo_nn's forecaster: quantile order, seeded determinism, and that the walk-forward trains it on the train
window only (the leak that would make a GPU result look better than it is). CPU only."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from tempo.backtest.features import frames_from_grid  # noqa: E402
from tempo.backtest.walkforward import make_windows, tempo_nn_model  # noqa: E402
from tempo.forecast.lgbm import FEATURES  # noqa: E402
from tempo.forecast.nn import NNQuantileForecaster  # noqa: E402
from tests.fixtures.synthetic import make_synthetic_market  # noqa: E402

START = pd.Timestamp("2026-01-05", tz="UTC")


def random_xy(n=600, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="30min", tz="UTC", name="target_time")
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURES))), columns=FEATURES, index=idx)
    y = pd.Series(50 + 10 * X["price_lag_1d"] + rng.normal(0, 5, n), index=idx)
    return X, y


def test_quantiles_are_ordered_and_indexed_by_target_time():
    X, y = random_xy()
    m = NNQuantileForecaster(device="cpu", max_epochs=40)
    m.fit(X, y)
    q = m.predict(X)
    assert list(q.columns) == ["p10", "p50", "p90"]
    assert q.index.equals(X.index)
    assert (q.p10 <= q.p50).all() and (q.p50 <= q.p90).all()


def test_same_seed_same_model():
    X, y = random_xy()
    a, b = (
        NNQuantileForecaster(device="cpu", seed=7, max_epochs=40),
        NNQuantileForecaster(device="cpu", seed=7, max_epochs=40),
    )
    a.fit(X, y)
    b.fit(X, y)
    pd.testing.assert_frame_equal(a.predict(X), b.predict(X), check_exact=True)


# --- train-window isolation (the mutation-checked test) ----------------------------------------------------


class Recording(NNQuantileForecaster):
    """Records every target_time it is trained on."""

    seen: list = []

    def fit(self, X, y):
        Recording.seen.append(X.index)
        super().fit(X, y)


@pytest.fixture(scope="module")
def synthetic():
    grid = make_synthetic_market()
    window = next(iter(make_windows(START, START + pd.Timedelta(days=60))))
    return grid, window


def fitted(frames, window):
    from tempo.backtest.walkforward import TempoModel

    Recording.seen = []
    model = TempoModel(frames, forecaster_factory=lambda: Recording(device="cpu", seed=0, max_epochs=40))
    return model.fit(window.train_start, window.test_start)


def test_trains_only_on_targets_before_the_test_week(synthetic):
    grid, window = synthetic
    fitted(frames_from_grid(grid), window)
    (index,) = Recording.seen
    assert len(index) > 1000
    assert index.max() < window.test_start  # no label from the test week


def test_test_week_prices_cannot_change_the_model(synthetic):
    """Rewrite every price in the test week: the fitted model must be identical (same predictions on the same
    rows). Any training row whose label or features came from the test week would change it."""
    grid, window = synthetic
    frames = frames_from_grid(grid)
    base = fitted(frames, window)
    shocked = frames_from_grid(grid)
    in_test = (shocked.prices.index >= window.test_start) & (shocked.prices.index < window.test_end)
    shocked.prices[in_test] = shocked.prices[in_test] * 10 + 500
    after = fitted(frames_from_grid_like(shocked), window)
    X, _ = random_xy()
    pd.testing.assert_frame_equal(base.predict(X), after.predict(X), check_exact=True)


def frames_from_grid_like(frames):
    """Rebuild Frames so the derived daily/weekly tables see the edited prices too."""
    from tempo.backtest.features import Frames

    return Frames(frames.prices, frames.forecasts, frames.mid_offsets)


def test_tempo_nn_model_uses_the_nn(synthetic):
    grid, window = synthetic
    model = tempo_nn_model(frames_from_grid(grid), device="cpu").fit(window.train_start, window.test_start)
    assert isinstance(model, NNQuantileForecaster)
