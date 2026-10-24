"""replay_week(): one backtest week, period by period, for the dashboard's Replay tab (docs/b.md item 3).

Owner: Ernqi.

Columns, as DbSource.replay_week() and its synthetic stand-in use them:
    ts           period start (UTC)
    actual       APX price, GBP/MWh
    p10/p50/p90  the tempo forecast, decided before the period's UK day began
    mw           the tempo schedule: + charge, - discharge, 0 hold
    soc_mwh      state of charge after the period
    cum_pnl_gbp  money made so far, net of cycle cost

The week is rebuilt with the backtest's own windows and TempoModel, so the last cum_pnl_gbp is that week's
pnl_gbp in backtest_results. Cycle cost is charged per MWh sold (simulate's cycles = MWh sold / capacity),
so the running total includes it as the battery sells, not as a lump at the end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tempo.backtest.walkforward import UK, TempoModel, Window, _slice
from tempo.sim.battery import Battery, simulate

COLUMNS = ["ts", "actual", "p10", "p50", "p90", "mw", "soc_mwh", "cum_pnl_gbp"]


def pick_week(results: pd.DataFrame, strategy: str = "tempo", regime: str = "windy") -> pd.Series:
    """The `regime` week where `strategy` scored the median of its `regime` weeks: typical, not the best."""
    weeks = results[(results.strategy == strategy) & (results.regime == regime)].sort_values("pct_of_perfect")
    if weeks.empty:
        raise ValueError(f"no {regime} weeks for {strategy} in these results")
    return weeks.iloc[(len(weeks) - 1) // 2]


def per_period_pnl(battery: Battery, mw: np.ndarray, prices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(soc_path, pnl per period net of wear). Sums to simulate(...).pnl_gbp."""
    sim = simulate(battery, mw, prices)
    s = np.sqrt(battery.rt_efficiency)
    delta = np.diff(np.concatenate([[battery.soc_mwh], sim.soc_path]))
    bought = np.where(delta > 0, delta / s, 0.0)  # MWh from the grid
    sold = np.where(delta < 0, -delta * s, 0.0)  # MWh to the grid
    wear = sold / battery.capacity_mwh * battery.cycle_cost_gbp
    return sim.soc_path, (sold - bought) * prices - wear


def replay_week(
    prices_hh: pd.DataFrame,
    window: Window,
    model: TempoModel,
    optimiser=None,
    battery: Battery | None = None,
) -> pd.DataFrame:
    """The tempo schedule and forecast for window's test week, as the backtest ran it."""
    from tempo.optimise.greedy import GreedyOptimiser

    battery = battery or Battery()
    train_df = _slice(prices_hh, window.train_start, window.train_end)
    test_df = _slice(prices_hh, window.test_start, window.test_end)
    mw = model.strategy(optimiser or GreedyOptimiser())(train_df, test_df, battery)

    key = (train_df.bucket.min(), test_df.bucket.min())
    local_day = test_df.bucket.dt.tz_convert(UK).dt.date
    bands = []
    for day in local_day.unique():
        day_times = pd.DatetimeIndex(test_df.bucket[(local_day == day).to_numpy()])
        q = model.forecast(key, day_times)  # cached: the same forecast the schedule was planned on
        bands.append(
            q if q is not None else pd.DataFrame(np.nan, index=day_times, columns=["p10", "p50", "p90"])
        )
    q = pd.concat(bands)

    prices = test_df.price.to_numpy()
    soc, pnl = per_period_pnl(battery, mw, prices)
    out = pd.DataFrame(
        {
            "ts": test_df.bucket.to_numpy(),
            "actual": prices,
            "p10": q.p10.to_numpy(),
            "p50": q.p50.to_numpy(),
            "p90": q.p90.to_numpy(),
            "mw": mw,
            "soc_mwh": soc,
            "cum_pnl_gbp": np.cumsum(pnl),
        }
    )
    out["ts"] = pd.to_datetime(out.ts, utc=True)
    return out[COLUMNS]
