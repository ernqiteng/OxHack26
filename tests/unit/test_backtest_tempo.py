"""tempo and tempo_lp in the walk-forward on the 60-day synthetic market (docs/b.md item 2)."""

import pandas as pd
import pytest

from tempo.backtest.features import frames_from_grid
from tempo.backtest.walkforward import (
    PERIODS_PER_DAY,
    STRATEGIES,
    TempoModel,
    make_windows,
    prices_hh_from_grid_raw,
    run_all,
)
from tests.fixtures.synthetic import make_synthetic_market

START = pd.Timestamp("2026-01-05", tz="UTC")
HALF_HOUR = pd.Timedelta(minutes=30)


@pytest.fixture(scope="module")
def grid():
    return make_synthetic_market()


@pytest.fixture(scope="module")
def frames(grid):
    return frames_from_grid(grid)


@pytest.fixture(scope="module")
def results(grid, frames):
    windows = make_windows(START, START + pd.Timedelta(days=60))
    return run_all(prices_hh_from_grid_raw(grid), grid, windows, run_id="test-tempo", frames=frames)


def test_frames_add_tempo_and_tempo_lp(results):
    assert set(results.strategy) == set(STRATEGIES) | {"tempo", "tempo_lp"}
    assert results.groupby("strategy").size().eq(4).all()


def test_no_week_beats_perfect(results):
    assert (results.pct_of_perfect <= 100 + 1e-6).all()


def test_tempo_lp_beats_persistence(results):
    """The fixture's windy weeks move night prices; LightGBM sees wind_fc, persistence only yesterday."""
    total = results.groupby("strategy").pnl_gbp.sum()
    assert total["tempo_lp"] > total["persistence_greedy"]


def test_without_frames_the_strategies_are_unchanged(grid):
    windows = make_windows(START, START + pd.Timedelta(days=60))
    plain = run_all(prices_hh_from_grid_raw(grid), grid, windows, run_id="t")
    assert set(plain.strategy) == set(STRATEGIES)


def test_training_labels_never_come_from_the_test_week(frames):
    """Every training target starts before test_start, and no decision is after it."""
    model = TempoModel(frames, n_estimators=10)
    train_start, test_start = START + pd.Timedelta(days=7), START + pd.Timedelta(days=35)
    model.fit(train_start, test_start)
    used = [f for (T, h), f in model._features.items() if f is not None and h == PERIODS_PER_DAY]
    assert used, "no training decisions were made"
    assert max(f.index.max() for f in used) < test_start
    assert min(T for (T, _), f in model._features.items() if f is not None) >= train_start


def test_test_day_forecast_is_decided_before_the_day(frames):
    model = TempoModel(frames, n_estimators=10)
    key = (START + pd.Timedelta(days=7), START + pd.Timedelta(days=35))
    day = pd.date_range(key[1], periods=PERIODS_PER_DAY, freq="30min")
    q = model.forecast(key, day)
    assert q.index.equals(day) and q.notna().all().all()
    decided = [T for (T, h) in model._features if h == len(day) and T >= key[1] - HALF_HOUR]
    assert decided == [day[0] - pd.Timedelta(minutes=1)]
