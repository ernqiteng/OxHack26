"""Export what the walk-forward reads from Tiger to parquet, once, read-only. Owner: Girik.

    python scripts/export_frames.py                # -> data/frames/ (gitignored)
    python scripts/export_frames.py --out DIR

Three SELECTs via tempo.backtest.features.load_frames (prices_hh, WINDFOR/NDF publications, MID offsets).
The output is copied to the GPU box, which never connects to Tiger.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.backtest.features import load_frames  # noqa: E402
from tempo.backtest.frames_io import save_frames  # noqa: E402
from tempo.db.conn import get_conn  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "frames")
    a = ap.parse_args()
    t0 = time.perf_counter()
    with get_conn() as conn:
        frames = load_frames(conn)
    paths = save_frames(frames, a.out)
    print(
        f"exported in {time.perf_counter() - t0:.0f}s: {len(frames.prices):,} prices "
        f"({frames.prices.index.min():%Y-%m-%d} to {frames.prices.index.max():%Y-%m-%d %H:%M}), "
        f"{len(frames.forecasts):,} forecast rows, {len(frames.mid_offsets):,} MID offsets"
    )
    for p in paths:
        print(f"  {p.name}: {p.stat().st_size / 2**20:.1f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
