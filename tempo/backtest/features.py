"""build_features() for the backtest, from in-memory frames instead of Tiger.

Owner: Ernqi. See docs/b.md item 2.

The walk-forward needs features at ~3,600 decision times; each build_features call is a round trip to
Tiger, so the backtest would take hours. FrameConn answers build_features' own SQL queries from frames
loaded once, so the backtest runs Girik's build_features unchanged: same fallbacks, same columns, same
point-in-time rules. Only the query answers are reimplemented here, one function per query, and
tests/db/test_backtest_features.py checks that FrameConn and the real database give identical features.

A query build_features sends that FrameConn does not know raises, so a new query in build.py cannot be
silently skipped.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from tempo.features import build
from tempo.features.build import LONDON, build_features


def _local_midnight(ts: pd.DatetimeIndex, days_back=0) -> pd.DatetimeIndex:
    """London midnight of each timestamp's local day, minus days_back days, as UTC. Done on the naive local
    clock so a day is a calendar day across clock changes, as time_bucket(..., 'Europe/London') does."""
    naive = ts.tz_convert(LONDON).tz_localize(None).normalize() - pd.to_timedelta(days_back, unit="D")
    return naive.tz_localize(LONDON).tz_convert("UTC")


def _plus_local_days(ts: pd.DatetimeIndex, days: int) -> pd.DatetimeIndex:
    naive = ts.tz_convert(LONDON).tz_localize(None) + pd.Timedelta(days=days)
    return naive.tz_localize(LONDON).tz_convert("UTC")


@dataclass
class Frames:
    """What build_features reads, loaded once.

    prices:      prices_hh as a Series of price indexed by bucket (UTC), NaN-free, sorted
    forecasts:   grid_raw rows for WINDFOR and NDF series N, every publication (start_time, available_at,
                 dataset, value)
    mid_offsets: available_at - start_time in whole minutes for APXMIDP rows, indexed by start_time
    """

    prices: pd.Series
    forecasts: pd.DataFrame
    mid_offsets: pd.Series
    daily: pd.DataFrame = field(init=False)
    weekly: pd.DataFrame = field(init=False)

    def __post_init__(self):
        self.prices = self.prices.dropna().sort_index()
        self.mid_offsets = self.mid_offsets.sort_index()
        p = self.prices
        # prices_daily: London day buckets with spread = max - min, plus n / sum / sum_sq for the week.
        day = _local_midnight(p.index)
        g = pd.DataFrame({"day": day, "price": p.to_numpy()}).groupby("day").price
        daily = pd.DataFrame(
            {
                "spread": g.max() - g.min(),
                "n": g.count(),
                "sum": g.sum(),
                "sum_sq": g.apply(lambda x: (x * x).sum()),
            }
        )
        daily["end"] = _plus_local_days(daily.index, 1)
        self.daily = daily
        # prices_weekly: London weeks from Monday, sample stddev over half-hours, as schema.sql computes it.
        week = _local_midnight(daily.index, daily.index.tz_convert(LONDON).dayofweek)
        w = daily.groupby(week)[["n", "sum", "sum_sq"]].sum()
        var = (w["sum_sq"] - w["sum"] ** 2 / w["n"]) / (w["n"] - 1).where(w["n"] > 1)
        stddev = np.sqrt(np.maximum(var.fillna(0.0), 0.0))  # greatest(NULL, 0) is 0 in Postgres, not NULL
        self.weekly = pd.DataFrame(
            {"mean": w["sum"] / w["n"], "stddev": stddev, "end": _plus_local_days(w.index, 7)}
        )
        self._fc = {}
        for name in ("WINDFOR", "NDF"):
            rows = self.forecasts[self.forecasts.dataset == name].sort_values(["start_time", "available_at"])
            naive = lambda c: c.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]")  # noqa: E731
            self._fc[name] = (naive(rows.start_time), naive(rows.available_at), rows.value.to_numpy(float))

    # --- one answer per build_features query -------------------------------------------------------

    def delay_guard(self, T):
        o = self.mid_offsets
        window = o[(o.index > T - pd.Timedelta(days=8)) & (o.index <= T)]
        return [(int(v),) for v in window.unique()]

    def price_lags(self, lag_buckets, cutoff):
        want = pd.DatetimeIndex(lag_buckets).tz_convert("UTC")
        found = self.prices.reindex(want[want <= cutoff]).dropna()
        return list(zip(found.index, found.to_numpy(), strict=True))

    def price_last(self, T, cutoff):
        p = self.prices
        window = p[(p.index >= T - pd.Timedelta(days=8)) & (p.index <= cutoff)]
        return [(window.index[-1], window.iloc[-1])] if len(window) else []

    def daily_rows(self, T, complete):
        d = self.daily
        rows = d[(d.index >= T - pd.Timedelta(days=10)) & (d.end <= complete)]
        return list(zip(rows.index, rows.spread, strict=True))

    def weekly_rows(self, T, complete):
        w = self.weekly
        rows = w[(w.index >= T - pd.Timedelta(days=21)) & (w.end <= complete)]
        if not len(rows):
            return []
        last = rows.iloc[-1]
        return [(rows.index[-1], last["mean"], last["stddev"])]

    def forecast_rows(self, dataset, fc_from, fc_to, T):
        """Latest publication at or before T for each start_time in [fc_from, fc_to]."""
        start, avail, value = self._fc[dataset]
        as64 = lambda t: np.datetime64(pd.Timestamp(t).tz_convert("UTC").tz_localize(None), "ns")  # noqa: E731
        i, j = np.searchsorted(start, as64(fc_from), "left"), np.searchsorted(start, as64(fc_to), "right")
        s, a, v = start[i:j], avail[i:j], value[i:j]
        keep = a <= as64(T)
        s, v = s[keep], v[keep]
        if not len(s):  # nothing published yet, as the SQL would return no rows
            return []
        last = np.r_[s[1:] != s[:-1], True]  # rows are sorted by (start, available_at): last per start wins
        return [(pd.Timestamp(t, tz="UTC"), float(x)) for t, x in zip(s[last], v[last], strict=True)]

    def answer(self, query: str, params: dict) -> list[tuple]:
        if query not in (*build.QUERIES.values(), build.Q_DELAY_GUARD):
            raise NotImplementedError(f"FrameConn does not answer this build_features query:\n{query}")
        T = pd.Timestamp(params["T"]).tz_convert("UTC")
        if query == build.Q_DELAY_GUARD:
            return self.delay_guard(T)
        cutoff = pd.Timestamp(params["cutoff"]).tz_convert("UTC")
        complete = pd.Timestamp(params["complete"]).tz_convert("UTC")
        if query == build.Q_PRICE_LAGS:
            return self.price_lags(params["lag_buckets"], cutoff)
        if query == build.Q_PRICE_LAST:
            return self.price_last(T, cutoff)
        if query == build.Q_DAILY:
            return self.daily_rows(T, complete)
        if query == build.Q_WEEKLY:
            return self.weekly_rows(T, complete)
        if query in (build.Q_WIND, build.Q_DEMAND):
            dataset = "WINDFOR" if query == build.Q_WIND else "NDF"
            return self.forecast_rows(dataset, params["fc_from"], params["fc_to"], T)
        raise AssertionError("unreachable: every known query is answered above")


class _Cursor:
    def __init__(self, frames: Frames):
        self.frames, self.rows = frames, []

    def execute(self, query, params):
        self.rows = self.frames.answer(query, params)

    def fetchall(self):
        return self.rows

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FrameConn:
    """Just enough of a psycopg connection for build_features."""

    def __init__(self, frames: Frames):
        self.frames = frames

    def cursor(self):
        return _Cursor(self.frames)

    def pipeline(self):
        return nullcontext()


def frames_from_grid(grid: pd.DataFrame) -> Frames:
    """Frames from grid_raw-shaped rows (e.g. tests/fixtures/synthetic.py), prices_hh as their mean MID."""
    mid = grid[(grid.dataset == "MID") & (grid.series == "APXMIDP")]
    prices = mid.groupby("start_time").value.mean()
    offsets = mid.groupby("start_time").apply(
        lambda g: int((g.available_at.max() - g.name).total_seconds() // 60), include_groups=False
    )
    fc = grid[(grid.dataset == "WINDFOR") | ((grid.dataset == "NDF") & (grid.series == build.DEMAND_SERIES))]
    return Frames(prices, fc[["start_time", "available_at", "dataset", "value"]].copy(), offsets)


Q_LOAD_PRICES = "SELECT bucket, price FROM prices_hh WHERE price IS NOT NULL ORDER BY bucket"
Q_LOAD_FORECASTS = """
SELECT start_time, available_at, dataset, value FROM grid_raw
WHERE dataset = 'WINDFOR' OR (dataset = 'NDF' AND series = %(demand_series)s)
"""
Q_LOAD_MID_OFFSETS = """
SELECT start_time, extract(epoch FROM available_at - start_time)::int / 60 FROM grid_raw
WHERE dataset = 'MID' AND series = %(series)s
"""


def load_frames(conn) -> Frames:
    """Everything build_features reads, from a real database, in three queries."""
    with conn.cursor() as cur:
        cur.execute(Q_LOAD_PRICES)
        p = pd.DataFrame(cur.fetchall(), columns=["bucket", "price"])
        cur.execute(Q_LOAD_FORECASTS, {"demand_series": build.DEMAND_SERIES})
        fc = pd.DataFrame(cur.fetchall(), columns=["start_time", "available_at", "dataset", "value"])
        cur.execute(Q_LOAD_MID_OFFSETS, {"series": build.PRICE_SERIES})
        off = pd.DataFrame(cur.fetchall(), columns=["start_time", "offset"])
    prices = pd.Series(
        p.price.astype(float).to_numpy(), index=pd.DatetimeIndex(pd.to_datetime(p.bucket, utc=True))
    )
    for col in ("start_time", "available_at"):
        fc[col] = pd.to_datetime(fc[col], utc=True)
    fc["value"] = fc.value.astype(float)
    offsets = pd.Series(
        off.offset.astype(int).to_numpy(), index=pd.DatetimeIndex(pd.to_datetime(off.start_time, utc=True))
    )
    return Frames(prices, fc, offsets)


def features_at(frames: Frames, decision_time: datetime, horizon: int = 48) -> pd.DataFrame:
    """build_features(decision_time) answered from frames, plus horizon_k (1..horizon)."""
    out = build_features(FrameConn(frames), decision_time, horizon)
    out["horizon_k"] = np.arange(1, len(out) + 1, dtype=float)
    return out
