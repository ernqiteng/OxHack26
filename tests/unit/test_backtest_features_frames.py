"""FrameConn without a database: the edge cases tests/db/test_backtest_features.py cannot reach cheaply."""

import pandas as pd
import pytest

from tempo.backtest.features import features_at, frames_from_grid
from tests.fixtures.synthetic import make_synthetic_market

START = pd.Timestamp("2026-01-05", tz="UTC")


@pytest.fixture(scope="module")
def grid():
    return make_synthetic_market(days=20)


def test_no_forecast_published_yet_raises_like_build_features(grid):
    """build_features raises ValueError when no WINDFOR is published for the horizon; so must FrameConn."""
    late = grid[(grid.dataset != "WINDFOR") | (grid.start_time >= START + pd.Timedelta(days=12))]
    with pytest.raises(ValueError, match="wind_fc"):
        features_at(frames_from_grid(late), START + pd.Timedelta(days=9))


def test_no_price_in_eight_days_raises(grid):
    with pytest.raises(ValueError, match="no APX price"):
        features_at(frames_from_grid(grid), START - pd.Timedelta(days=1))


def test_unknown_query_is_refused(grid):
    with pytest.raises(NotImplementedError):
        frames_from_grid(grid).answer("SELECT 1", {"T": START})


def test_features_use_only_published_prices(grid):
    """Changing every price from 40 minutes before T onwards changes nothing (MID publishes at +40 min)."""
    T = START + pd.Timedelta(days=10, hours=12)
    base = features_at(frames_from_grid(grid), T)
    edited = grid.copy()
    later = (edited.dataset == "MID") & (edited.start_time > T - pd.Timedelta(minutes=40))
    edited.loc[later, "value"] = 9999.0
    pd.testing.assert_frame_equal(features_at(frames_from_grid(edited), T), base)
