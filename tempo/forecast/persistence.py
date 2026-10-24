"""PersistenceForecaster: p50 = same period yesterday, band from rolling std.

Owner: Ernqi. See docs/ernqi.md Phase 2 task 1.

Uses two of Girik's build_features columns (docs/girik.md Phase 2 task 2):
    price_lag_1d   APX price at the same period one day before the target   -> p50
    weekly_std     standard deviation of price over the last week           -> band width
p10 / p90 = p50 -/+ k * weekly_std, with k fitted on the training rows so that 80% of actual prices
fall inside the band: k is the 80th percentile of |actual - p50| / weekly_std. The band is symmetric,
so coverage is honest overall; it does not try to be skewed like real price spikes.
"""

import numpy as np
import pandas as pd

MIN_STD = 1e-6  # a flat week would give a zero-width band; never divide by zero


class PersistenceForecaster:
    def __init__(self, coverage: float = 0.8):
        self.coverage = coverage
        self.k: float | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        p50, std = X["price_lag_1d"].to_numpy(float), np.maximum(X["weekly_std"].to_numpy(float), MIN_STD)
        z = np.abs(np.asarray(y, dtype=float) - p50) / std
        z = z[np.isfinite(z)]
        if len(z) == 0:
            raise ValueError("no training rows with both a price and a price_lag_1d")
        self.k = float(np.quantile(z, self.coverage))

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.k is None:
            raise RuntimeError("fit() first: k sets the band width")
        p50 = X["price_lag_1d"].to_numpy(float)
        half = self.k * np.maximum(X["weekly_std"].to_numpy(float), MIN_STD)
        return pd.DataFrame({"p10": p50 - half, "p50": p50, "p90": p50 + half}, index=X.index)
