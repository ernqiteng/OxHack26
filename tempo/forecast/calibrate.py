"""Conformal recalibration of the p10-p90 band: offset(), widen(), rolling_offsets().

The LightGBM band is too narrow: it should hold 80% of real prices and holds about 40% live (63% on the
training holdout). Each settled forecast gets a score s = max(p10 - actual, actual - p90): negative inside
the band, the miss in £/MWh outside it. Moving both edges out by the 80% quantile of recent scores makes the
band hold about 80% of the next prices, as long as the next errors look like the recent ones (split
conformal, as in conformalised quantile regression).

p50 never moves, so the greedy optimiser and the default LP make exactly the same decisions. Only the LP's
conservative mode (buy at p90, sell at p10) reads the band edges.

Nothing here is wired into the live decider: scripts/backtest.py --calibration and
scripts/calibration_report.py use it offline.
"""

import math

import numpy as np
import pandas as pd

COVERAGE = 0.8  # p10-p90
MIN_SCORES = 48  # fewer settled forecasts than one day's: no offset yet


def scores(p10, p90, actual) -> np.ndarray:
    p10, p90, actual = (np.asarray(a, dtype=float) for a in (p10, p90, actual))
    return np.maximum(p10 - actual, actual - p90)


def offset(s, coverage: float = COVERAGE) -> float:
    """The ceil((n + 1) * coverage)-th smallest score: the finite-sample conformal quantile. Negative when the
    band is already too wide, which narrows it."""
    s = np.sort(np.asarray(s, dtype=float)[np.isfinite(s)])
    if len(s) == 0:
        raise ValueError("no scores to calibrate on")
    k = min(len(s), math.ceil((len(s) + 1) * coverage))
    return float(s[k - 1])


def widen(quantiles: pd.DataFrame, off: float) -> pd.DataFrame:
    """p10 - off and p90 + off, clipped at p50 so p10 <= p50 <= p90 still holds."""
    out = quantiles.copy()
    out["p10"] = np.minimum(quantiles.p10 - off, quantiles.p50)
    out["p90"] = np.maximum(quantiles.p90 + off, quantiles.p50)
    return out


def rolling_offsets(
    rows: pd.DataFrame, published_by, lookback: pd.Timedelta, coverage: float = COVERAGE
) -> pd.Series:
    """One offset per decision time, using only forecasts that were settled by then.

    rows: decided_at, target_time, p10, p90, actual. published_by(target_time) is when that target's actual
    price was first known. A decision at T uses rows decided in [T - lookback, T) whose actual was published
    by T. NaN where fewer than MIN_SCORES rows qualify."""
    rows = rows.assign(
        score=scores(rows.p10, rows.p90, rows.actual),
        known_at=published_by(pd.DatetimeIndex(rows.target_time)),
    ).dropna(subset=["score"])
    out = {}
    for t in sorted(rows.decided_at.unique()):
        t = pd.Timestamp(t)
        pool = rows[(rows.decided_at >= t - lookback) & (rows.decided_at < t) & (rows.known_at <= t)]
        out[t] = offset(pool.score, coverage) if len(pool) >= MIN_SCORES else np.nan
    return pd.Series(out, dtype=float).rename_axis("decided_at")
