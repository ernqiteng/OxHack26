"""tempo_nn walk-forward on the GPU box, from parquet only (the box never connects to Tiger). Owner: Girik.

    python scripts/backtest_nn.py --frames data/frames --out out/ --device cuda

1. Rebuilds the same 100 walk-forward windows as run db-20261024T202144Z (data start .. --end 2026-10-24,
   28 training days, 7-day test weeks) and runs tempo_nn on the MOST RECENT 30 test weeks only.
2. Timing: trains the tempo_nn models of 10 windows on cuda and on cpu, same box, same data, same seeds,
   with the features computed once beforehand so only training is timed (a "10-window job").

Writes out/results_tempo_nn.parquet (backtest_results rows, run_id filled in later on the laptop) and
out/gpu_runs.json.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.backtest.frames_io import load_frames_dir  # noqa: E402
from tempo.backtest.walkforward import make_windows, run_strategy, tempo_nn_model  # noqa: E402
from tempo.optimise.greedy import GreedyOptimiser  # noqa: E402

ORIGINAL_RUN = "db-20261024T202144Z"


def windows_like_original(frames, end: pd.Timestamp) -> list:
    start = frames.prices.index.min().ceil("D")
    windows = list(make_windows(start, end))
    if len(windows) != 100:
        raise SystemExit(f"expected the original run's 100 windows, got {len(windows)} (data start {start})")
    return windows


def time_training(frames, windows, device: str) -> float:
    """Wall seconds to train one tempo_nn model per window on `device`, features already cached."""
    import torch

    warm = tempo_nn_model(frames, device="cpu")
    for w in windows:  # compute (and cache) every training feature row once, untimed
        warm.fit(w.train_start, w.test_start)
    model = tempo_nn_model(frames, device=device)
    model._features = warm._features  # noqa: SLF001 - share the cache so only training is timed
    if device == "cuda":
        torch.zeros(1, device="cuda").sum().item()  # CUDA context start-up, untimed
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    for w in windows:
        model.fit(w.train_start, w.test_start)
    if device == "cuda":
        torch.cuda.synchronize()
    return time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--end", default="2026-10-24", help="end of the original run's data (exclusive)")
    ap.add_argument("--last-weeks", type=int, default=30)
    ap.add_argument("--timing-windows", type=int, default=10)
    a = ap.parse_args()
    import torch

    a.out.mkdir(parents=True, exist_ok=True)
    frames = load_frames_dir(a.frames)
    prices_hh = pd.DataFrame({"bucket": frames.prices.index, "price": frames.prices.to_numpy()})
    windows = windows_like_original(frames, pd.Timestamp(a.end, tz="UTC"))
    recent = windows[-a.last_weeks :]
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    print(f"windows: {len(windows)}; tempo_nn on the last {len(recent)} ({recent[0].test_start:%Y-%m-%d} to "
          f"{recent[-1].test_end:%Y-%m-%d}); device {a.device}; GPU {gpu_name}", flush=True)  # fmt: skip

    t0 = time.perf_counter()
    model = tempo_nn_model(frames, device=a.device)
    rows = run_strategy("tempo_nn", prices_hh, recent, model.strategy(GreedyOptimiser()), run_id="pending")
    run_s = time.perf_counter() - t0
    pd.DataFrame(rows).to_parquet(a.out / "results_tempo_nn.parquet", index=False)
    print(f"tempo_nn: {len(rows)} weeks in {run_s:.0f}s", flush=True)

    timing_windows = recent[: a.timing_windows]
    runs = []
    for device in ("cuda", "cpu"):
        if device == "cuda" and not torch.cuda.is_available():
            continue
        secs = time_training(frames, timing_windows, device)
        runs.append({
            "job": f"tempo_nn training, {len(timing_windows)}-window job (one model per walk-forward window)",
            "device": device, "wall_seconds": round(secs, 2),
            "gpu_name": gpu_name if device == "cuda" else None,
            "cpu_threads": torch.get_num_threads(), "n_models": len(timing_windows), "run_id": None,
        })  # fmt: skip
        print(f"timing {device}: {secs:.2f}s for {len(timing_windows)} models", flush=True)
    (a.out / "gpu_runs.json").write_text(json.dumps(runs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
