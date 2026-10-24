"""make_training_set(): point-in-time feature/target pairs built through build_features().

Owner: Ernqi (Part A, docs/a.md item 1), written by Ayo.

Every row of X is one (decision_time, target_time) pair whose features come from
`build_features(conn, decision_time)` and nothing else, so the training set cannot see the future by
construction. `horizon_k` is k in `target_time = floor(decision_time) + 30 min * k`, k = 1..48, the same
definition `run_decision` uses (docs/a.md, shared rules). y is the realised APX price at target_time from
`prices_hh`, NaN where the period has not settled yet (LightGBM's fit() drops those rows).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tempo.features.build import FEATURE_COLUMNS, build_features, target_times

log = logging.getLogger(__name__)

HALF_HOUR = pd.Timedelta(minutes=30)
TRAINING_COLUMNS = [*FEATURE_COLUMNS, "horizon_k"]


def decision_times(start: datetime, end: datetime, every: timedelta = timedelta(hours=6)) -> list[datetime]:
    """Decision times from `start` up to and including `end`, `every` apart. Both must be tz-aware."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware (UTC)")
    out, t = [], start
    while t <= end:
        out.append(t)
        t += every
    return out


def add_horizon_k(features: pd.DataFrame, decision_time: datetime) -> pd.DataFrame:
    """Append horizon_k = number of half-hours from floor(decision_time) to each target (1..48)."""
    t0 = pd.Timestamp(decision_time).tz_convert("UTC").floor("30min")
    k = ((features.index - t0) / HALF_HOUR).astype(int)
    if (k < 1).any():
        raise ValueError("target_time before decision_time: horizon_k must be >= 1")
    out = features.copy()
    out["horizon_k"] = k.astype(float)
    return out


def realised_prices(conn, start: datetime, end: datetime) -> dict[pd.Timestamp, float]:
    rows = conn.execute(
        "SELECT bucket, price FROM prices_hh WHERE bucket >= %s AND bucket <= %s AND price IS NOT NULL",
        (start, end),
    ).fetchall()
    return {pd.Timestamp(b).tz_convert("UTC"): float(p) for b, p in rows}


def make_training_set(
    conn,
    decision_times: Iterable[datetime],
    horizon: int = 48,
    *,
    strict: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Features and realised prices for every (decision_time, target_time) pair.

    Returns X indexed by a (decision_time, target_time) MultiIndex with TRAINING_COLUMNS, and y aligned
    to it. With strict=False, decision times that build_features refuses (no price in the previous
    8 days, no forecast yet) are skipped with a log line instead of raising, which is what training on a
    data set with a ragged start wants.
    """
    times: Sequence[datetime] = list(decision_times)
    if not times:
        raise ValueError("no decision times")
    frames: list[pd.DataFrame] = []
    skipped = 0
    for dt in times:
        try:
            feats = build_features(conn, dt, horizon)
        except ValueError as exc:
            if strict:
                raise
            skipped += 1
            log.info("skipping %s: %s", dt, exc)
            continue
        feats = add_horizon_k(feats, dt)
        feats.insert(0, "decision_time", pd.Timestamp(dt).tz_convert("UTC"))
        frames.append(feats.reset_index())
    if not frames:
        raise ValueError(f"every one of the {len(times)} decision times was unusable")
    if skipped:
        log.info("skipped %d of %d decision times", skipped, len(times))
    X = pd.concat(frames, ignore_index=True).set_index(["decision_time", "target_time"])
    X = X[TRAINING_COLUMNS].astype(float)

    targets = X.index.get_level_values("target_time")
    prices = realised_prices(conn, targets.min().to_pydatetime(), targets.max().to_pydatetime())
    y = pd.Series([prices.get(t, np.nan) for t in targets], index=X.index, name="price", dtype=float)
    return X, y


def first_usable_decision_time(conn, lead_days: int = 8) -> datetime | None:
    """The earliest decision time build_features can serve: `lead_days` after the first price."""
    first = conn.execute("SELECT min(bucket) FROM prices_hh").fetchone()[0]
    if first is None:
        return None
    t = pd.Timestamp(first).tz_convert("UTC") + pd.Timedelta(days=lead_days)
    return t.ceil("6h").to_pydatetime()


__all__ = [
    "TRAINING_COLUMNS",
    "add_horizon_k",
    "decision_times",
    "first_usable_decision_time",
    "make_training_set",
    "target_times",
]
