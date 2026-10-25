"""Conformal recalibration of the band (tempo/forecast/calibrate.py) and band_check in the walk-forward."""

import numpy as np
import pandas as pd
import pytest

from tempo.backtest.features import frames_from_grid
from tempo.backtest.walkforward import (
    TempoModel,
    band_check,
    band_coverage,
    make_windows,
    prices_hh_from_grid_raw,
    run_strategy,
    tempo_strategies,
)
from tempo.forecast.calibrate import offset, rolling_offsets, scores, widen
from tempo.optimise.lp import LPOptimiser
from tests.fixtures.synthetic import make_synthetic_market

START = pd.Timestamp("2026-01-05", tz="UTC")


def test_offset_covers_80_pct_of_fresh_errors():
    """A band that is £10 too narrow on each side gets about £10 back."""
    rng = np.random.default_rng(0)
    y = rng.normal(0, 20, 20_000)
    half = 20 * 1.2816 - 10  # true p90 of N(0, 20) is 25.6; this band is 10 too narrow
    off = offset(scores(-half, half, y[:10_000]))
    assert off == pytest.approx(10, abs=1)
    fresh = y[10_000:]
    assert np.mean(np.abs(fresh) <= half + off) == pytest.approx(0.8, abs=0.015)


def test_offset_is_negative_when_the_band_is_too_wide():
    y = np.random.default_rng(1).normal(0, 1, 5_000)
    assert offset(scores(-5, 5, y)) < 0


def test_widen_keeps_order_and_never_moves_p50():
    q = pd.DataFrame({"p10": [90.0, 99.0], "p50": [100.0, 100.0], "p90": [110.0, 101.0]})
    wide, narrow = widen(q, 5), widen(q, -3)
    pd.testing.assert_series_equal(wide.p50, q.p50)
    assert list(wide.p10) == [85, 94] and list(wide.p90) == [115, 106]
    assert (narrow.p10 <= narrow.p50).all() and (narrow.p50 <= narrow.p90).all()
    assert list(narrow.p90) == [107, 100]  # clipped at p50


def test_rolling_offsets_only_use_prices_published_by_the_decision():
    """A batch's offset ignores a later batch's huge miss, and its own unsettled targets."""
    t0 = pd.Timestamp("2026-01-01", tz="UTC")
    rows = []
    for b, miss in [(0, 1.0), (1, 1.0), (2, 1000.0)]:
        decided = t0 + pd.Timedelta(days=2 * b)  # two days apart, so a batch's day has settled
        for k in range(48):
            rows.append((decided, decided + pd.Timedelta(minutes=30 * k), 0.0, 10.0, 10.0 + miss))
    rows = pd.DataFrame(rows, columns=["decided_at", "target_time", "p10", "p90", "actual"])
    off = rolling_offsets(rows, lambda t: t + pd.Timedelta(minutes=40), pd.Timedelta(days=7))
    assert np.isnan(off.iloc[0])  # nothing settled before the first batch
    assert off.iloc[1] == pytest.approx(1.0)  # batch 0's 48 targets had all settled
    assert off.iloc[2] == pytest.approx(1.0)  # batch 2's own misses aren't known when it is made


@pytest.fixture(scope="module")
def synthetic():
    grid = make_synthetic_market()
    prices = prices_hh_from_grid_raw(grid)
    model = TempoModel(frames_from_grid(grid), n_estimators=30)
    windows = list(make_windows(START, START + pd.Timedelta(days=60)))
    for name, fn in tempo_strategies(None, model=model).items():
        run_strategy(name, prices, windows, fn)  # fills the model's caches, as run_all does
    return model, prices, windows, band_check(model, prices, windows)


def test_band_check_rows_and_offsets(synthetic):
    model, prices, windows, band = synthetic
    assert set(band.week_start) == {w.test_start.date() for w in windows}
    assert band.offset.isna().any()  # the first test day has no settled history
    assert band.offset.notna().sum() > len(band) / 2
    assert set(model.offsets) == set(band.decided_at + pd.Timedelta(minutes=1))
    assert (band.p10_cal <= band.p50).all() and (band.p50 <= band.p90_cal).all()


def test_recalibrated_band_is_closer_to_80_pct(synthetic):
    c = band_coverage(synthetic[3])
    assert abs(c["recalibrated"] - 0.8) < abs(c["raw"] - 0.8)


def test_calibrated_strategy_needs_band_check_first(synthetic):
    model, prices, windows, _ = synthetic
    rows = run_strategy(
        "safe_cal", prices, windows, model.strategy(LPOptimiser(conservative=True), calibrated=True)
    )
    assert len(rows) == len(windows)
    fresh = TempoModel(model.frames, n_estimators=30)
    with pytest.raises(KeyError, match="band_check"):
        run_strategy(
            "x", prices, windows[:1], fresh.strategy(LPOptimiser(conservative=True), calibrated=True)
        )
