"""make_windows: test weeks tile the range, never overlap, and train always ends where test begins."""

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from tempo.backtest.walkforward import make_windows

START = pd.Timestamp("2026-01-05", tz="UTC")


@given(st.integers(0, 400), st.integers(0, 60), st.integers(1, 14))
def test_windows_tile_without_overlap(days, train_days, test_days):
    end = START + pd.Timedelta(days=days)
    windows = list(make_windows(START, end, train_days, test_days))
    for w in windows:
        assert w.train_end == w.test_start  # train ends before test starts (exclusive end)
        assert w.train_end - w.train_start == pd.Timedelta(days=train_days)
        assert w.test_end - w.test_start == pd.Timedelta(days=test_days)
        assert w.train_start >= START and w.test_end <= end
    for a, b in zip(windows, windows[1:]):
        assert a.test_end == b.test_start  # contiguous, no gaps, no overlap
    if windows:
        assert windows[0].test_start == START + pd.Timedelta(days=train_days)
    # only a partial final week is dropped
    covered_until = windows[-1].test_end if windows else START + pd.Timedelta(days=train_days)
    assert end - covered_until < pd.Timedelta(days=test_days)


def test_sixty_synthetic_days_give_four_test_weeks():
    windows = list(make_windows(START, START + pd.Timedelta(days=60)))
    assert [w.test_start.date().isoformat() for w in windows] == [
        "2026-02-02",
        "2026-02-09",
        "2026-02-16",
        "2026-02-23",
    ]
