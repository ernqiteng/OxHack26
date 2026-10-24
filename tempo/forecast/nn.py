"""NNQuantileForecaster: a small MLP with p10/p50/p90 heads, pinball loss, same interface as LightGBM.

Owner: Ernqi (stub), written by Girik for the GPU run (25 Oct). Kept only if it beats LightGBM on unseen
weeks; the walk-forward reports it either way and the live decider stays on LightGBM.

Same contract as LightGBMQuantileForecaster: fit(X, y) / predict(X) -> DataFrame p10, p50, p90 sorted per row,
indexed like X (target_time). Same FEATURES (build_features columns + horizon_k).

Deliberately small and untuned (speed version): standardise X and y on the training rows only, two hidden
layers, Adam, up to MAX_EPOCHS full-batch epochs with early stopping on the LAST 15% of the training rows
(still inside the training window, so nothing from a test week is ever seen). Seeded; on CPU with
deterministic algorithms the same rows give the same model. device = cuda if available, else cpu.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tempo.forecast.lgbm import FEATURES, QUANTILES

HIDDEN = 32
MAX_EPOCHS = 300
PATIENCE = 20
LR = 1e-2
VAL_FRACTION = 0.15
# A feature constant in the training window (std below this) keeps scale 1 instead of ~0. Otherwise a tiny
# change at test time explodes: hours_since_last_price is constant at the 6-hourly training decisions and one
# minute different at test decisions, which gave z = 16,700 and p50 forecasts of £10,000+/MWh.
MIN_STD = 1e-3


def _torch():
    import torch  # optional extra "nn": imported lazily so tempo imports without it

    return torch


def pinball(pred, y, alphas):
    """Mean pinball (quantile) loss over the quantile heads. pred: (n, q), y: (n, 1), alphas: (q,)."""
    diff = y - pred
    return (alphas * diff).clamp(min=0).add(((alphas - 1) * diff).clamp(min=0)).mean()


class NNQuantileForecaster:
    def __init__(
        self,
        features: list[str] | None = None,
        *,
        device: str | None = None,
        seed: int = 0,
        hidden: int = HIDDEN,
        max_epochs: int = MAX_EPOCHS,
        patience: int = PATIENCE,
    ):
        self.features = list(features or FEATURES)
        self.device = device
        self.seed = seed
        self.hidden = hidden
        self.max_epochs = max_epochs
        self.patience = patience
        self.model = None
        self.epochs_run = 0

    def _matrix(self, X: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.features if c not in X.columns]
        if missing:
            raise KeyError(f"feature columns missing from X: {missing}")
        return X[self.features].to_numpy(dtype=np.float32)

    def _device(self, torch):
        return self.device or ("cuda" if torch.cuda.is_available() else "cpu")

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        torch = _torch()
        Xf, yv = self._matrix(X), np.asarray(y, dtype=np.float32)
        keep = np.isfinite(yv) & np.isfinite(Xf).all(axis=1)
        if not keep.any():
            raise ValueError("no training rows with a realised price")
        Xf, yv = Xf[keep], yv[keep]

        # Scale on the training rows only (the caller passes only training-window rows).
        std = Xf.std(axis=0)
        self.x_mean, self.x_std = Xf.mean(axis=0), np.where(std < MIN_STD, 1.0, std) + 1e-6
        self.y_mean, self.y_std = float(yv.mean()), float(yv.std() + 1e-6)
        Xs, ys = (Xf - self.x_mean) / self.x_std, (yv - self.y_mean) / self.y_std

        dev = self._device(torch)
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)
        # Process-wide switch, so set it on every fit: deterministic on cpu; off on cuda, where cuBLAS would
        # need CUBLAS_WORKSPACE_CONFIG (a cpu fit earlier in the process must not break a cuda fit).
        torch.use_deterministic_algorithms(dev == "cpu")
        n_val = max(1, int(len(Xs) * VAL_FRACTION)) if len(Xs) >= 20 else 0
        X_t = torch.tensor(Xs, device=dev)
        y_t = torch.tensor(ys, device=dev).unsqueeze(1)
        X_tr, y_tr = (X_t[:-n_val], y_t[:-n_val]) if n_val else (X_t, y_t)
        X_va, y_va = (X_t[-n_val:], y_t[-n_val:]) if n_val else (X_t, y_t)
        alphas = torch.tensor(list(QUANTILES.values()), device=dev)

        model = torch.nn.Sequential(
            torch.nn.Linear(Xs.shape[1], self.hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(self.hidden, self.hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(self.hidden, len(QUANTILES)),
        ).to(dev)
        opt = torch.optim.Adam(model.parameters(), lr=LR)
        best, best_state, bad = float("inf"), None, 0
        epoch = 0
        for epoch in range(self.max_epochs):  # noqa: B007 - epochs_run below
            model.train()
            opt.zero_grad()
            loss = pinball(model(X_tr), y_tr, alphas)
            loss.backward()
            opt.step()
            model.eval()
            with torch.no_grad():
                val = float(pinball(model(X_va), y_va, alphas))
            if val < best - 1e-6:
                best, bad = val, 0
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            else:
                bad += 1
                if bad >= self.patience:
                    break
        self.epochs_run = epoch + 1
        model.load_state_dict(best_state)
        model.eval()
        self.model, self._dev = model, dev

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.model is None:
            raise RuntimeError("fit() first")
        torch = _torch()
        Xs = (self._matrix(X) - self.x_mean) / self.x_std
        with torch.no_grad():
            out = self.model(torch.tensor(Xs, device=self._dev)).cpu().numpy().astype(float)
        raw = out * self.y_std + self.y_mean
        return pd.DataFrame(np.sort(raw, axis=1), columns=list(QUANTILES), index=X.index)
