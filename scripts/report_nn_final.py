"""Report the final GPU run: tables, checks and a bootstrap CI. Reads Tiger (read-only), writes nothing there.
Owner: Girik.

    python scripts/report_nn_final.py --results data/gpu_out_final/results_final.parquet

Stored rows of run db-20261024T202144Z: simple_rule, persistence, tempo, tempo_lp and perfect; the box gives
tempo_nn (A), tempo_nn_ens (B), tempo_avg (C) and a recompute of tempo/tempo_lp, which is only compared.
Checks: no week beats perfect; the box's perfect pnl equals the stored one for every week.
Groups: the 30 most recent test weeks (evaluated once before: a second look), the 70 earlier weeks (NOT clean
for the NN: the scaling bug was found and fixed on them), and all 100 pooled.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.db.conn import get_conn, run_sql  # noqa: E402

ORIGINAL_RUN = "db-20261024T202144Z"
ROWS = [
    ("simple_rule", "simple rule", "stored"),
    ("persistence_greedy", "persistence", "stored"),
    ("tempo", "tempo (LightGBM)", "stored"),
    ("tempo_lp", "tempo_lp (LightGBM + LP)", "stored"),
    ("tempo_nn", "A tempo_nn (1 seed)", "box"),
    ("tempo_nn_ens", "B tempo_nn_ens (5 seeds)", "box"),
    ("tempo_avg", "C tempo_avg (LightGBM + NN)", "box"),
]


def pooled(df: pd.DataFrame) -> float:
    return 100 * df.pnl_gbp.sum() / df.perfect_pnl_gbp.sum()


def bootstrap_gap(pnl: np.ndarray, ref: np.ndarray, perfect: np.ndarray, n=10_000, seed=0) -> tuple:
    """95% CI of pooled % of perfect (strategy - reference), resampling weeks with replacement."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    gaps = 100 * (pnl[idx].sum(1) - ref[idx].sum(1)) / perfect[idx].sum(1)
    return tuple(np.percentile(gaps, [2.5, 97.5]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, required=True)
    a = ap.parse_args()
    box = pd.read_parquet(a.results)
    box["week_start"] = pd.to_datetime(box.week_start).dt.date
    cols = ["week_start", "strategy", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"]
    with get_conn() as conn:
        stored = pd.DataFrame(
            run_sql(
                conn, f"SELECT {', '.join(cols)} FROM backtest_results WHERE run_id = %s", (ORIGINAL_RUN,)
            ),
            columns=cols,
        )
    stored["week_start"] = pd.to_datetime(stored.week_start).dt.date
    for c in ("pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"):
        stored[c] = stored[c].astype(float)

    weeks = sorted(stored.week_start.unique())
    assert len(weeks) == 100, len(weeks)
    assert sorted(box.week_start.unique()) == weeks, "box weeks differ from the stored run"
    perfect = stored[stored.strategy == "perfect"].set_index("week_start").perfect_pnl_gbp
    gap = (box.perfect_pnl_gbp - box.week_start.map(perfect)).abs()
    print(f"check perfect pnl, box vs stored: max gap £{gap.max():.4f} over {len(box)} rows")
    assert gap.max() < 0.01
    for name, df in (("stored", stored), ("box", box)):
        over = df[df.pnl_gbp > df.perfect_pnl_gbp + 1e-6]
        print(f"check no week beats perfect ({name}): {len(over)} rows above perfect")
        assert over.empty

    print("\nrecompute vs stored (pnl per week):")
    for s in ("tempo", "tempo_lp"):
        mine = box[box.strategy == f"{s}_recomputed"].set_index("week_start").pnl_gbp
        ref = stored[stored.strategy == s].set_index("week_start").pnl_gbp.reindex(mine.index)
        d = (mine - ref).abs()
        print(f"  {s}: {int((d > 0.01).sum())} of {len(d)} weeks differ by > £0.01 (max £{d.max():.2f});"
              f" pooled {pooled(box[box.strategy == f'{s}_recomputed']):.1f}% vs stored "
              f"{pooled(stored[stored.strategy == s]):.1f}%")  # fmt: skip

    devices = box.groupby("strategy").device.first()
    print("\ndevice per box strategy:")
    for s, d in devices.items():
        print(f"  {s}: {d}")

    table = pd.concat(
        [
            stored[stored.strategy.isin([r[0] for r in ROWS if r[2] == "stored"])],
            box[box.strategy.isin([r[0] for r in ROWS if r[2] == "box"])][cols],
        ],  # fmt: skip
        ignore_index=True,
    )
    tempo = table[table.strategy == "tempo"].set_index("week_start").pnl_gbp
    groups = {
        "30 recent (2nd look)": weeks[-30:],
        "70 earlier (NOT clean for NN)": weeks[:-30],
        "all 100": weeks,
    }
    print()
    header = "strategy".ljust(30) + "".join(f"| {g:<34}" for g in groups)
    print(header)
    print(" " * 30 + "| %perf  >tempo  worst week         " * len(groups))
    for key, label, _ in ROWS:
        df = table[table.strategy == key].set_index("week_start")
        line = label.ljust(30)
        for wk in groups.values():
            g = df.loc[df.index.isin(wk)]
            beat = "-" if key == "tempo" else str(int((g.pnl_gbp > tempo.reindex(g.index) + 1e-9).sum()))
            worst = g.pct_of_perfect.idxmin()
            line += f"| {pooled(g):5.1f}  {beat:>6}  {g.pct_of_perfect.min():6.1f}% {worst} "
        print(line)

    print("\nbootstrap, all 100 weeks: pooled % of perfect minus tempo's, 95% CI (10,000 resamples of weeks)")
    ref = tempo.reindex(weeks).to_numpy()
    perf = perfect.reindex(weeks).to_numpy()
    for key, label, _ in ROWS[3:]:
        pnl = table[table.strategy == key].set_index("week_start").pnl_gbp.reindex(weeks).to_numpy()
        lo, hi = bootstrap_gap(pnl, ref, perf)
        point = 100 * (pnl.sum() - ref.sum()) / perf.sum()
        print(f"  {label:<30} {point:+5.1f} pts  [{lo:+5.1f}, {hi:+5.1f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
