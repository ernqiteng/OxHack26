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


# Columns lgbm_frame() can make from the fixture. The rest of FEATURES (price_last_known,
# hours_since_last_price, daily_spread_lag_1d, lag_missing, fc_missing) need a decision time; build_features has one.
LGBM_FIXTURE_FEATURES = [
    "price_lag_1d", "price_lag_7d", "weekly_mean", "weekly_std", "wind_fc", "demand_fc", "wind_share_fc",
    "hour", "dow", "is_weekend", "period_of_day", "horizon_k",
]


def lgbm_frame(days: int = 62) -> pd.DataFrame:
    """persistence_frame() plus the fixture's wind and demand, UK clock columns, and a horizon_k that
    cycles 1..48. Index target_time; `price` is the actual, every other column is in LGBM_FIXTURE_FEATURES."""
    grid = make_synthetic_market(days=days)
    prices = prices_hh_from_grid_raw(grid).set_index("bucket").price
    frame = pd.DataFrame({"price": prices})
    frame["price_lag_1d"] = prices.shift(freq="1D").reindex(prices.index)
    frame["price_lag_7d"] = prices.shift(freq="7D").reindex(prices.index)
    week_before = prices.shift(freq="1D").rolling("7D")
    frame["weekly_mean"] = week_before.mean().reindex(prices.index)
    frame["weekly_std"] = week_before.std().reindex(prices.index)
    series = lambda d: grid[grid.dataset == d].set_index("start_time").value  # noqa: E731
    frame["wind_fc"] = series("WINDFOR").reindex(prices.index, method="ffill")  # hourly -> half-hourly
    frame["demand_fc"] = series("NDF").reindex(prices.index)
    frame["wind_share_fc"] = frame.wind_fc / frame.demand_fc
    local = prices.index.tz_convert("Europe/London")
    frame["hour"] = local.hour
    frame["dow"] = local.dayofweek
    frame["is_weekend"] = local.dayofweek >= 5
    frame["period_of_day"] = local.hour * 2 + local.minute // 30 + 1
    frame["horizon_k"] = [i % 48 + 1 for i in range(len(frame))]
    frame.index.name = "target_time"
    return frame.iloc[8 * 48 :]
