"""replay_week on the synthetic market: its numbers are the backtest's numbers (docs/b.md item 3)."""

import numpy as np
import pandas as pd
import pytest

from tempo.backtest.features import frames_from_grid
from tempo.backtest.replay import COLUMNS, per_period_pnl, pick_week, replay_week
from tempo.backtest.walkforward import TempoModel, make_windows, prices_hh_from_grid_raw, run_all
from tempo.sim.battery import Battery, simulate
from tests.fixtures.synthetic import make_synthetic_market

START = pd.Timestamp("2026-01-05", tz="UTC")


@pytest.fixture(scope="module")
def setup():
    grid = make_synthetic_market()
    prices = prices_hh_from_grid_raw(grid)
    frames = frames_from_grid(grid)
    windows = list(make_windows(START, START + pd.Timedelta(days=60)))
    model = TempoModel(frames)
    results = run_all(prices, grid, windows, "t", strategies={"tempo": model.strategy(_greedy())})
    return prices, windows, model, results


def _greedy():
    from tempo.optimise.greedy import GreedyOptimiser

    return GreedyOptimiser()


@pytest.fixture(scope="module")
def week(setup):
    prices, windows, model, results = setup
    row = pick_week(results)
    window = next(w for w in windows if w.test_start.date() == row.week_start)
    return row, replay_week(prices, window, model)


def test_shape_matches_the_dashboard(week):
    _, df = week
    assert df.columns.tolist() == COLUMNS
    assert len(df) == 7 * 48
    assert df.ts.is_monotonic_increasing and str(df.ts.dt.tz) == "UTC"


def test_final_cumulative_pnl_is_the_backtest_pnl(week):
    row, df = week
    assert df.cum_pnl_gbp.iloc[-1] == pytest.approx(row.pnl_gbp, abs=1e-6)


def test_bands_are_ordered_and_filled(week):
    _, df = week
    assert df[["p10", "p50", "p90"]].notna().all().all()
    assert ((df.p10 <= df.p50) & (df.p50 <= df.p90)).all()


def test_soc_stays_in_bounds_and_matches_simulate(week):
    _, df = week
    b = Battery()
    assert df.soc_mwh.between(0, b.capacity_mwh).all()
    np.testing.assert_allclose(df.soc_mwh, simulate(b, df.mw.to_numpy(), df.actual.to_numpy()).soc_path)


def test_pick_week_is_the_median_windy_week_not_the_best():
    r = pd.DataFrame(
        {
            "strategy": "tempo",
            "regime": ["windy", "windy", "windy", "calm", "windy"],
            "week_start": [1, 2, 3, 4, 5],
            "pct_of_perfect": [90.0, 40.0, 60.0, 99.0, 70.0],
        }
    )
    assert pick_week(r).week_start == 3  # windy scores 40, 60, 70, 90: lower median is 60


def test_per_period_pnl_sums_to_simulate():
    rng = np.random.default_rng(0)
    b = Battery(soc_mwh=0.7)
    mw, prices = rng.uniform(-1.2, 1.2, 96), rng.uniform(-20, 200, 96)
    _, pnl = per_period_pnl(b, mw, prices)
    assert pnl.sum() == pytest.approx(simulate(b, mw, prices).pnl_gbp, abs=1e-9)


def test_dbsource_reads_the_stored_week(tmp_path, monkeypatch):
    from tempo.dashboard import data

    stored = data.SyntheticSource().replay_week().assign(actual=123.0)
    path = tmp_path / "replay_week.parquet"
    stored.to_parquet(path, index=False)
    monkeypatch.setattr(data, "REPLAY_WEEK_PATH", path)
    src = data.DbSource(None)
    week = src.replay_week()
    assert (week.actual == 123.0).all() and week.columns.tolist() == stored.columns.tolist()
    assert "replay_week" not in src.notes


def test_dbsource_falls_back_with_a_note_when_no_week_is_stored(tmp_path, monkeypatch):
    from tempo.dashboard import data

    monkeypatch.setattr(data, "REPLAY_WEEK_PATH", tmp_path / "missing.parquet")
    src = data.DbSource(None)
    assert not src.replay_week().empty
    assert "scripts/replay_week.py" in src.notes["replay_week"]


def test_the_committed_week_has_the_dashboard_shape():
    from tempo.dashboard import data

    if not data.REPLAY_WEEK_PATH.exists():
        pytest.skip("no stored replay week")
    week = pd.read_parquet(data.REPLAY_WEEK_PATH)
    assert week.columns.tolist() == COLUMNS and len(week) == 7 * 48
    assert ((week.p10 <= week.p50) & (week.p50 <= week.p90)).all()
