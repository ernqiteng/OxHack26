"""Walk-forward backtest on the 60-day synthetic market: perfect is 100%, nothing beats it, known answers hold."""

import numpy as np
import pandas as pd
import pytest

from tempo.backtest.walkforward import (
    STRATEGIES,
    Window,
    make_windows,
    persistence_greedy,
    pct_of_perfect,
    prices_hh_from_grid_raw,
    run_all,
    run_strategy,
    simple_rule,
)
from tempo.sim.battery import Battery
from tests.fixtures.synthetic import make_synthetic_market

START = pd.Timestamp("2026-01-05", tz="UTC")


@pytest.fixture(scope="module")
def grid():
    return make_synthetic_market()


@pytest.fixture(scope="module")
def prices_hh(grid):
    return prices_hh_from_grid_raw(grid)


@pytest.fixture(scope="module")
def results(grid, prices_hh):
    windows = make_windows(START, START + pd.Timedelta(days=60))
    return run_all(prices_hh, grid, windows, run_id="test-synthetic")


def test_one_row_per_week_and_strategy(results):
    assert len(results) == 4 * len(STRATEGIES)
    assert not results.duplicated(["run_id", "week_start", "strategy"]).any()  # backtest_results primary key
    assert list(results.columns) == [
        "run_id", "week_start", "strategy", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect", "regime",
    ]


def test_perfect_is_100_pct_every_week(results):
    assert results[results.strategy == "perfect"].pct_of_perfect.to_numpy() == pytest.approx(100.0, abs=1e-6)


def test_nothing_beats_perfect(results):
    assert (results.pct_of_perfect <= 100.0 + 1e-6).all()


def test_simple_rule_positive_on_calm_weeks(results):
    calm = results[(results.strategy == "simple_rule") & (results.regime == "calm")]
    assert len(calm) > 0 and (calm.pnl_gbp > 0).all()


def test_regimes_follow_the_windy_even_weeks(results):
    """Fixture: even ISO weeks are windy. Test weeks are ISO 6, 7, 8, 9."""
    by_week = results.drop_duplicates("week_start").set_index("week_start").regime
    assert [by_week[w] for w in sorted(by_week.index)] == ["windy", "calm", "windy", "calm"]


def test_known_answers_from_fixture_docstring(prices_hh):
    """First 7 days, no training window: simple rule 1264.8, perfect 1399.6 (tests/fixtures/synthetic.py)."""
    week1 = [Window(START, START, START, START + pd.Timedelta(days=7))]
    simple = run_strategy("simple_rule", prices_hh, week1, simple_rule)[0]
    assert simple["pnl_gbp"] == pytest.approx(1264.8, abs=0.1)
    assert simple["perfect_pnl_gbp"] == pytest.approx(1399.6, abs=0.1)


def test_persistence_greedy_uses_only_published_prices(prices_hh):
    """Change prices after each day's decision time: the plan for that day must not move.
    Day d is planned at local midnight, so it may only depend on prices published by then."""
    window = Window(START, START + pd.Timedelta(days=28), START + pd.Timedelta(days=28), START + pd.Timedelta(days=35))
    train = prices_hh[(prices_hh.bucket >= window.train_start) & (prices_hh.bucket < window.train_end)].reset_index(drop=True)
    test = prices_hh[(prices_hh.bucket >= window.test_start) & (prices_hh.bucket < window.test_end)].reset_index(drop=True)
    base = persistence_greedy(train, test, Battery(soc_mwh=0.0))

    # Scramble everything from 23:30 on the last training day onwards (published 00:40, after the first decision).
    scrambled = test.copy()
    scrambled["price"] = np.random.default_rng(0).permutation(test.price.to_numpy())
    train_scrambled = train.copy()
    train_scrambled.loc[train_scrambled.index[-1], "price"] = 999.0
    changed = persistence_greedy(train_scrambled, scrambled, Battery(soc_mwh=0.0))
    assert changed[:48] == pytest.approx(base[:48])  # day 1 decided before any of that was published


def test_pct_of_perfect_edge_cases():
    assert pct_of_perfect(50.0, 100.0) == 50.0
    assert pct_of_perfect(0.0, 0.0) == 100.0
    assert pct_of_perfect(-5.0, 0.0) == 0.0
