"""make_windows(), run_strategy(), strategies: simple_rule, persistence_greedy, tempo, tempo_lp, perfect.

Owner: Ernqi. See docs/ernqi.md Phase 1 task 5.

Walk-forward: test weeks tile the range, each preceded by its training window, never overlapping.
Every test week starts from a fresh default Battery, so weeks are independent and each is scored
against perfect foresight on that same week.

A strategy is strategy_fn(train_df, test_df, battery) -> schedule_mw for the test week. Both frames are
prices_hh shaped (bucket, price). test_df holds the week's actual prices: strategies may use them only
to track the battery's real state of charge and for prices already published at decision time
(MID is published at start + 30 min + MID_DELAY). perfect is the one strategy allowed to see them all.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from tempo.optimise.greedy import GreedyOptimiser
from tempo.optimise.perfect import perfect_foresight
from tempo.sim.battery import Battery, simulate

UK = "Europe/London"
MID_DELAY = timedelta(minutes=10)  # MID_AVAILABILITY_DELAY_MIN, docs/needs.md B8 item 4
PERIODS_PER_DAY = 48

StrategyFn = Callable[[pd.DataFrame, pd.DataFrame, Battery], np.ndarray]


@dataclass(frozen=True)
class Window:
    train_start: pd.Timestamp
    train_end: pd.Timestamp  # exclusive, == test_start
    test_start: pd.Timestamp
    test_end: pd.Timestamp  # exclusive


def make_windows(start, end, train_days: int = 28, test_days: int = 7) -> Iterator[Window]:
    """Test windows of test_days tile [start + train_days, end); a final partial window is dropped."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    test_start = start + pd.Timedelta(days=train_days)
    while test_start + pd.Timedelta(days=test_days) <= end:
        test_end = test_start + pd.Timedelta(days=test_days)
        yield Window(test_start - pd.Timedelta(days=train_days), test_start, test_start, test_end)
        test_start = test_end


def prices_hh_from_grid_raw(grid: pd.DataFrame) -> pd.DataFrame:
    """The prices_hh view (bucket, price) built from grid_raw-format rows, e.g. the synthetic fixture."""
    mid = grid[(grid.dataset == "MID") & (grid.series == "APXMIDP")]
    out = mid.groupby("start_time", as_index=False).value.mean()
    return out.rename(columns={"start_time": "bucket", "value": "price"}).sort_values("bucket", ignore_index=True)


# --- strategies ----------------------------------------------------------------


def simple_rule(train_df: pd.DataFrame, test_df: pd.DataFrame, battery: Battery) -> np.ndarray:
    """Charge 01:00 to 05:00, discharge 17:00 to 19:00, UK local time, every day."""
    hour = test_df.bucket.dt.tz_convert(UK).dt.hour.to_numpy()
    return np.where((hour >= 1) & (hour < 5), battery.power_mw, np.where((hour >= 17) & (hour < 19), -battery.power_mw, 0.0))


def persistence_greedy(train_df: pd.DataFrame, test_df: pd.DataFrame, battery: Battery) -> np.ndarray:
    """Each day at local midnight: forecast = same period yesterday, greedy plan, carry SoC to the next day."""
    history = pd.concat([train_df, test_df], ignore_index=True)
    published = history.set_index("bucket").price
    publish_time = published.index + pd.Timedelta(minutes=30) + MID_DELAY

    schedule = np.zeros(len(test_df))
    soc = battery.soc_mwh
    local_day = test_df.bucket.dt.tz_convert(UK).dt.date
    for day in local_day.unique():
        rows = np.flatnonzero((local_day == day).to_numpy())
        day_times = pd.DatetimeIndex(test_df.bucket.iloc[rows])
        decision_time = day_times[0]
        known = published[publish_time <= decision_time]
        forecast = known.reindex(day_times - pd.Timedelta(days=1), method="ffill").to_numpy()
        if np.isnan(forecast).all():  # nothing published yet (first day without training data): hold
            continue
        forecast = pd.Series(forecast).ffill().bfill().to_numpy()
        day_battery = Battery(**{**battery.__dict__, "soc_mwh": soc})
        quantiles = pd.DataFrame({"p50": forecast}, index=day_times)
        mw = GreedyOptimiser().plan(quantiles, day_battery).mw.to_numpy()
        schedule[rows] = mw
        soc = simulate(day_battery, mw, test_df.price.to_numpy()[rows]).soc_path[-1]  # real SoC, not forecast
    return schedule


def perfect(train_df: pd.DataFrame, test_df: pd.DataFrame, battery: Battery) -> np.ndarray:
    return perfect_foresight(test_df.price.to_numpy(), battery).mw.to_numpy()


STRATEGIES: dict[str, StrategyFn] = {
    "simple_rule": simple_rule,
    "persistence_greedy": persistence_greedy,
    "perfect": perfect,
}


# --- running and regimes -------------------------------------------------------


def _slice(prices_hh: pd.DataFrame, start, end) -> pd.DataFrame:
    return prices_hh[(prices_hh.bucket >= start) & (prices_hh.bucket < end)].reset_index(drop=True)


def run_strategy(
    name: str,
    prices_hh: pd.DataFrame,
    windows,
    strategy_fn: StrategyFn,
    run_id: str = "backtest",
    battery: Battery | None = None,
    regimes: dict | None = None,
) -> list[dict]:
    """One backtest_results row per test window. Use a new run_id per run: (run_id, week_start, strategy)
    is the table's primary key."""
    battery = battery or Battery()
    regimes = regimes or {}
    rows = []
    for w in windows:
        train_df, test_df = _slice(prices_hh, w.train_start, w.train_end), _slice(prices_hh, w.test_start, w.test_end)
        prices = test_df.price.to_numpy()
        pnl = simulate(battery, strategy_fn(train_df, test_df, battery), prices).pnl_gbp
        best = simulate(battery, perfect(train_df, test_df, battery), prices).pnl_gbp
        rows.append(
            {
                "run_id": run_id,
                "week_start": w.test_start.date(),
                "strategy": name,
                "pnl_gbp": pnl,
                "perfect_pnl_gbp": best,
                "pct_of_perfect": pct_of_perfect(pnl, best),
                "regime": regimes.get(w.test_start.date()),
            }
        )
    return rows


def pct_of_perfect(pnl: float, perfect_pnl: float) -> float:
    if abs(perfect_pnl) < 1e-9:  # nothing could be earned: holding is perfect, anything else is not
        return 100.0 if pnl >= -1e-9 else 0.0
    return round(100.0 * pnl / perfect_pnl, 9)  # perfect / perfect is 100.00000000000001 in floats otherwise


def weekly_regimes(grid: pd.DataFrame, windows) -> dict:
    """'windy' if the week's mean wind share of demand (WINDFOR / NDF) is above the median week, else 'calm'.
    If NDF does not cover every test week, the whole run uses mean WINDFOR MW instead, so one run has one
    definition. Uses the latest published forecast for each start_time. Keyed by test week start date."""
    def latest(dataset):
        rows = grid[grid.dataset == dataset].sort_values("available_at")
        return rows.groupby("start_time").value.last()

    def weekly_mean(series):
        return {
            w.test_start.date(): series[(series.index >= w.test_start) & (series.index < w.test_end)].mean()
            for w in windows
        }

    wind, demand = weekly_mean(latest("WINDFOR")), weekly_mean(latest("NDF"))
    if all(pd.notna(v) for v in demand.values()):
        shares = {week: wind[week] / demand[week] for week in wind}
    else:
        shares = wind
    known = [v for v in shares.values() if pd.notna(v)]
    if not known:
        return {}
    median = np.median(known)
    return {week: ("windy" if share > median else "calm") for week, share in shares.items() if pd.notna(share)}


def run_all(prices_hh, grid, windows, run_id, strategies=None, battery=None) -> pd.DataFrame:
    windows = list(windows)
    regimes = weekly_regimes(grid, windows) if grid is not None else {}
    rows = []
    for name, fn in (strategies or STRATEGIES).items():
        rows += run_strategy(name, prices_hh, windows, fn, run_id=run_id, battery=battery, regimes=regimes)
    return pd.DataFrame(rows)


def write_results(conn, results: pd.DataFrame) -> int:
    """Insert into backtest_results. Fails on a repeated (run_id, week_start, strategy): use a new run_id."""
    cols = ["run_id", "week_start", "strategy", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect", "regime"]
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO backtest_results ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
            [tuple(r) for r in results[cols].itertuples(index=False)],
        )
    return len(results)
