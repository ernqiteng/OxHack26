"""Test-only stand-in for the two build_features columns persistence needs, from synthetic prices.

Not a feature builder: Girik's tempo/features/build.py is the real one (docs/girik.md Phase 2 task 2).
This only lets the forecaster tests run before it exists. Rows without a full week of history are dropped.
"""

import pandas as pd

from tempo.backtest.walkforward import prices_hh_from_grid_raw
from tests.fixtures.synthetic import make_synthetic_market


def persistence_frame(days: int = 60) -> pd.DataFrame:
    """Index target_time; columns price (actual), price_lag_1d, weekly_std (std of the 7 days before)."""
    prices = prices_hh_from_grid_raw(make_synthetic_market(days=days)).set_index("bucket").price
    frame = pd.DataFrame({"price": prices})
    frame["price_lag_1d"] = prices.shift(freq="1D").reindex(prices.index)
    frame["weekly_std"] = prices.shift(freq="1D").rolling("7D").std().reindex(prices.index)
    frame.index.name = "target_time"
    return frame.iloc[8 * 48 :]
