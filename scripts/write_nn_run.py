"""Write the GPU run to Tiger: every row of run db-20261024T202144Z copied to a fresh run_id, plus tempo_nn's
30 weeks from the box. Owner: Girik. The only Tiger write of the GPU step.

    python scripts/write_nn_run.py --results out/results_tempo_nn.parquet --timing out/gpu_runs.json
    python scripts/write_nn_run.py ... --dry-run        # checks and comparison, no write

tempo, tempo_lp and the baselines are not recomputed: they are copied, so the dashboard (which shows the
latest run) still has every strategy. Checks before writing: tempo_nn never beats perfect in a week; its
perfect pnl equals the original run's for the same week (same data, same windows); regime labels come from
the original run, so they are the 100-week labels, not a 30-week median.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.backtest.walkforward import write_results  # noqa: E402
from tempo.db.conn import get_conn, run_sql  # noqa: E402

ORIGINAL_RUN = "db-20261024T202144Z"
COLUMNS = ["run_id", "week_start", "strategy", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect", "regime"]


def merge(original: pd.DataFrame, nn: pd.DataFrame, run_id: str) -> pd.DataFrame:
    """The new run: original rows + tempo_nn rows, all under run_id. Raises if any check fails."""
    nn = nn.copy()
    nn["week_start"] = pd.to_datetime(nn.week_start).dt.date
    original = original.copy()
    original["week_start"] = pd.to_datetime(original.week_start).dt.date
    if (nn.pnl_gbp > nn.perfect_pnl_gbp + 1e-6).any() or (nn.pct_of_perfect > 100 + 1e-9).any():
        raise ValueError("tempo_nn beats perfect foresight in a week: a lookahead leak, not writing")
    perfect = original[original.strategy == "perfect"].set_index("week_start")
    missing = set(nn.week_start) - set(perfect.index)
    if missing:
        raise ValueError(f"tempo_nn weeks not in {ORIGINAL_RUN}: {sorted(missing)}")
    gap = (nn.set_index("week_start").perfect_pnl_gbp - perfect.perfect_pnl_gbp.reindex(nn.week_start)).abs()
    if (gap > 0.01).any():
        raise ValueError(f"perfect pnl differs from {ORIGINAL_RUN} by up to £{gap.max():.2f}: different data")
    nn["regime"] = perfect.regime.reindex(nn.week_start).to_numpy()
    out = pd.concat([original, nn], ignore_index=True)
    out["run_id"] = run_id
    return out[COLUMNS]


def comparison(run: pd.DataFrame) -> dict:
    """tempo vs tempo_nn on the weeks tempo_nn ran (pooled pnl / perfect pnl, like the honesty table)."""
    weeks = set(run[run.strategy == "tempo_nn"].week_start)
    same = run[run.week_start.isin(weeks)]
    out = {"weeks": len(weeks)}
    for s in ("tempo", "tempo_nn"):
        r = same[same.strategy == s]
        out[s] = round(100 * r.pnl_gbp.sum() / r.perfect_pnl_gbp.sum(), 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--timing", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run_id = f"gpu-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"  # sorts after db-…, so it becomes the latest run
    with get_conn() as conn:
        cols = ", ".join(COLUMNS)
        original = pd.DataFrame(
            run_sql(conn, f"SELECT {cols} FROM backtest_results WHERE run_id = %s", (ORIGINAL_RUN,)),
            columns=COLUMNS,
        )
        run = merge(original, pd.read_parquet(a.results), run_id)
        cmp = comparison(run)
        print(f"{run_id}: {len(run)} rows ({len(original)} copied + {len(run) - len(original)} tempo_nn)")
        print(f"same {cmp['weeks']} weeks: tempo {cmp['tempo']}% vs tempo_nn {cmp['tempo_nn']}% of perfect")
        if a.dry_run:
            print("dry run: nothing written")
            return 0
        print(f"wrote {write_results(conn, run)} rows to backtest_results")
    timing = json.loads(a.timing.read_text())
    for t in timing:
        t["run_id"] = run_id
    target = Path(__file__).resolve().parents[1] / "models" / "gpu_runs.json"
    target.write_text(json.dumps({"run_id": run_id, "comparison_30_weeks": cmp, "timing": timing}, indent=2))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
