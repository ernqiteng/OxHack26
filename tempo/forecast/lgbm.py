"""LightGBMQuantileForecaster: three quantile models (p10, p50, p90), sorted per row.

Owner: Ernqi. See docs/ernqi.md Phase 2 task 2.

One LGBMRegressor(objective='quantile', alpha=a) per a in (0.1, 0.5, 0.9), small trees. Features are
Girik's build_features columns (docs/girik.md Phase 2 task 2) plus horizon_k, the number of half-hours
from decision time to target. Quantile models are fitted independently, so their outputs can cross;
predict() sorts the three per row so p10 <= p50 <= p90 always holds.

Training is deterministic by default (seed 0, deterministic=True, one thread): the same rows give
the same model, which the backtest and the tests rely on.
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}

FEATURES = [
    "price_lag_1d",
    "price_lag_7d",
    "price_last_known",
    "hours_since_last_price",
    "lag_missing",
    "daily_spread_lag_1d",
    "weekly_mean",
    "weekly_std",
    "wind_fc",
    "demand_fc",
    "wind_share_fc",
    "hour",
    "dow",
    "is_weekend",
    "period_of_day",
    "horizon_k",
]

PARAMS = {
    "n_estimators": 300,
    "num_leaves": 15,
    "learning_rate": 0.05,
    "random_state": 0,  # LightGBM's seed=0; n_jobs is its num_threads
    "n_jobs": 1,
    "deterministic": True,
    "force_row_wise": True,  # deterministic=True needs a fixed histogram layout
    "verbose": -1,
}


class LightGBMQuantileForecaster:
    def __init__(self, features: list[str] | None = None, **params):
        self.features = list(features or FEATURES)
        self.params = {**PARAMS, **params}
        self.models: dict[str, LGBMRegressor] = {}

    def _matrix(self, X: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in self.features if c not in X.columns]
        if missing:
            raise KeyError(f"feature columns missing from X: {missing}")
        return X[self.features].astype(float)  # bool flags (lag_missing, is_weekend) as 0/1

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        Xf, y = self._matrix(X), np.asarray(y, dtype=float)
        keep = np.isfinite(y)
        if not keep.any():
            raise ValueError("no training rows with a realised price")
        self.models = {
            name: LGBMRegressor(objective="quantile", alpha=alpha, **self.params).fit(Xf[keep], y[keep])
            for name, alpha in QUANTILES.items()
        }

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if not self.models:
            raise RuntimeError("fit() or load() first")
        Xf = self._matrix(X)
        raw = np.column_stack([self.models[name].predict(Xf) for name in QUANTILES])
        return pd.DataFrame(np.sort(raw, axis=1), columns=list(QUANTILES), index=X.index)

    def save(self, directory: str | Path) -> list[Path]:
        """Write lgbm_p10.joblib, lgbm_p50.joblib, lgbm_p90.joblib into directory."""
        if not self.models:
            raise RuntimeError("nothing to save: fit() first")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        for name, model in self.models.items():
            paths.append(directory / f"lgbm_{name}.joblib")
            joblib.dump(model, paths[-1])
        return paths

    @classmethod
    def load(cls, directory: str | Path) -> "LightGBMQuantileForecaster":
        """Inverse of save(). Feature names come from the saved models, so they always match."""
        models = {name: joblib.load(Path(directory) / f"lgbm_{name}.joblib") for name in QUANTILES}
        features = list(models["p50"].feature_name_)
        if any(list(m.feature_name_) != features for m in models.values()):
            raise ValueError(f"saved models in {directory} were trained on different features")
        params = {k: v for k, v in models["p50"].get_params().items() if k not in ("objective", "alpha")}
        out = cls(features=features, **params)
        out.models = models
        return out
