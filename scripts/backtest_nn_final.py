"""The final GPU run: LightGBM, the neural net and two pre-declared NN variants on all 100 walk-forward weeks,
from parquet only (the box never connects to Tiger). Owner: Girik.

    python scripts/backtest_nn_final.py --frames data/frames --out out --device cuda
    python scripts/backtest_nn_final.py ... --features data/features.pkl   # reuse precomputed features
    python scripts/backtest_nn_final.py ... --save-features data/features.pkl --features-only

Same 100 windows as run db-20261024T202144Z (28 training days, 7-day test weeks, data to 2026-10-24).
Pre-declared variants, each run once:
    tempo_nn      A: single seed (0), the NN with the scaling fix          (trained on --device)
    tempo_nn_ens  B: mean of seeds 0-4 per window, one batched pass        (trained on --device)
    tempo_avg     C: mean of LightGBM's and tempo_nn's forecasts, greedy   (LightGBM on cpu, NN on --device)
Plus tempo and tempo_lp recomputed (LightGBM on cpu, n_jobs=1 as in the original run) to check stored rows.
Timing: variant B's training (5 seeds x 100 windows), features computed beforehand, on cuda and on cpu.

Writes out/results_final.parquet (one row per strategy and week, with the device that trained it) and
out/timing_final.json.
"""

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.backtest.frames_io import load_frames_dir  # noqa: E402
from tempo.backtest.walkforward import (  # noqa: E402
    AveragedTempoModel,
    TempoModel,
    make_windows,
    run_strategy,
    tempo_nn_ens_model,
    tempo_nn_model,
)
from tempo.optimise.greedy import GreedyOptimiser  # noqa: E402
from tempo.optimise.lp import LPOptimiser  # noqa: E402


def windows_like_original(frames, end: pd.Timestamp) -> list:
    start = frames.prices.index.min().ceil("D")
    windows = list(make_windows(start, end))
    if len(windows) != 100:
        raise SystemExit(f"expected the original run's 100 windows, got {len(windows)} (data start {start})")
    return windows


def time_ensemble_training(frames, features, windows, device: str) -> float:
    import torch

    model = tempo_nn_ens_model(frames, device=device)
    model._features = features  # noqa: SLF001 - shared cache, so only training is timed
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
    ap.add_argument("--features", type=Path, help="precomputed feature cache (pickle) to reuse")
    ap.add_argument("--save-features", type=Path)
    ap.add_argument("--features-only", action="store_true")
    ap.add_argument("--limit", type=int, help="smoke test only: the first N windows")
    a = ap.parse_args()
    import torch

    torch.set_num_threads(os.cpu_count() or 1)
    a.out.mkdir(parents=True, exist_ok=True)
    frames = load_frames_dir(a.frames)
    prices_hh = pd.DataFrame({"bucket": frames.prices.index, "price": frames.prices.to_numpy()})
    windows = windows_like_original(frames, pd.Timestamp(a.end, tz="UTC"))[: a.limit]
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    nn_dev = a.device if a.device != "cuda" or gpu else sys.exit("--device cuda but no GPU")
    nn_label = f"{nn_dev} ({gpu})" if nn_dev == "cuda" else f"{nn_dev} ({torch.get_num_threads()} threads)"
    first, last = windows[0].test_start, windows[-1].test_end
    print(f"{len(windows)} windows, weeks {first:%Y-%m-%d} to {last:%Y-%m-%d}; NN on {nn_label}", flush=True)
    phases = {}
    from importlib.metadata import version

    libs = {p: version(p) for p in ("torch", "pandas", "numpy", "lightgbm", "scipy", "highspy")}
    print(f"libraries: {libs}", flush=True)

    features = {}
    if a.features:
        features = pickle.loads(a.features.read_bytes())  # noqa: S301 - our own file, made by --features-only
    print(f"feature cache: {len(features)} decision rows", flush=True)

    def fresh_lgbm():
        m = TempoModel(frames)
        m._features = features  # noqa: SLF001 - one shared, point-in-time feature cache for every model
        return m

    if a.features_only:  # LightGBM + greedy over every window touches exactly the features every model needs
        t0 = time.perf_counter()
        run_strategy("tempo", prices_hh, windows, fresh_lgbm().strategy(GreedyOptimiser()))
        a.save_features.write_bytes(pickle.dumps(features))
        print(f"features: {len(features)} decision rows in {time.perf_counter() - t0:.0f}s", flush=True)
        return 0

    rows = []

    def run(name, model, optimiser, device):
        t = time.perf_counter()
        r = run_strategy(name, prices_hh, windows, model.strategy(optimiser), run_id="pending")
        secs = round(time.perf_counter() - t, 1)
        for x in r:
            x["device"] = device
        rows.extend(r)
        phases[f"{name}_s"] = secs
        print(f"{name}: {len(r)} weeks in {secs}s on {device}", flush=True)

    lgbm = fresh_lgbm()
    run("tempo_recomputed", lgbm, GreedyOptimiser(), "cpu (LightGBM, n_jobs=1)")
    run("tempo_lp_recomputed", lgbm, LPOptimiser(), "cpu (LightGBM, n_jobs=1)")  # same fits as above
    nn = tempo_nn_model(frames, device=nn_dev)
    nn._features = features  # noqa: SLF001
    run("tempo_nn", nn, GreedyOptimiser(), nn_label)
    ens = tempo_nn_ens_model(frames, device=nn_dev)
    ens._features = features  # noqa: SLF001
    run("tempo_nn_ens", ens, GreedyOptimiser(), nn_label)
    run("tempo_avg", AveragedTempoModel(lgbm, nn), GreedyOptimiser(), f"LightGBM cpu + NN {nn_label}")
    pd.DataFrame(rows).to_parquet(a.out / "results_final.parquet", index=False)

    timing = []
    for device in ("cuda", "cpu"):
        if device == "cuda" and not gpu:
            continue
        secs = time_ensemble_training(frames, features, windows, device)
        timing.append({
            "job": f"variant B training: 5 seeds x {len(windows)} windows ({5 * len(windows)} models)",
            "device": device, "device_name": gpu if device == "cuda" else f"{os.cpu_count()} vCPU",
            "torch_threads": torch.get_num_threads(), "wall_seconds": round(secs, 2),
        })  # fmt: skip
        print(f"timing {device}: {secs:.2f}s", flush=True)
    out = {"timing": timing, "phases": phases, "libraries": libs, "nn_device": nn_label}
    (a.out / "timing_final.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
