"""Save and load the walk-forward Frames as parquet, so the GPU box needs no database access.

Owner: Girik. The GPU run reads Tiger once (scripts/export_frames.py), copies three parquet files to the box
and never holds the DSN. Frames.__post_init__ re-derives daily/weekly from prices, so only the three inputs
are stored.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tempo.backtest.features import Frames

FILES = ("prices.parquet", "forecasts.parquet", "mid_offsets.parquet")


def save_frames(frames: Frames, directory: str | Path) -> list[Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    frames.prices.rename("price").rename_axis("bucket").reset_index().to_parquet(d / FILES[0], index=False)
    frames.forecasts.to_parquet(d / FILES[1], index=False)
    frames.mid_offsets.rename("offset").rename_axis("start_time").reset_index().to_parquet(
        d / FILES[2], index=False
    )
    return [d / f for f in FILES]


def load_frames_dir(directory: str | Path) -> Frames:
    d = Path(directory)
    p = pd.read_parquet(d / FILES[0])
    fc = pd.read_parquet(d / FILES[1])
    off = pd.read_parquet(d / FILES[2])
    prices = pd.Series(
        p.price.to_numpy(dtype=float), index=pd.DatetimeIndex(pd.to_datetime(p.bucket, utc=True))
    )
    for col in ("start_time", "available_at"):
        fc[col] = pd.to_datetime(fc[col], utc=True)
    offsets = pd.Series(
        off.offset.to_numpy(dtype=int), index=pd.DatetimeIndex(pd.to_datetime(off.start_time, utc=True))
    )
    return Frames(prices, fc, offsets)
