"""Store one windy backtest week for the dashboard's Replay tab: models/replay_week.parquet (+ .json).

Owner: Ernqi. See docs/b.md item 3.

    python scripts/replay_week.py                  # latest backtest run with tempo rows, median windy week
    python scripts/replay_week.py --run-id db-...  # a specific run

The week is the windy week where tempo scored the median of its windy weeks in that run (typical, not the
best). It is rebuilt with the backtest's windows and model, and the script refuses to write unless the
week's final cumulative PnL matches that run's pnl_gbp for the week to the penny.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.backtest import connect, load_db  # noqa: E402
from tempo.backtest.replay import pick_week, replay_week  # noqa: E402
from tempo.backtest.walkforward import TempoModel, make_windows  # noqa: E402

OUT = ROOT / "models" / "replay_week.parquet"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", help="backtest run to take the week from (default: latest with tempo rows)")
    ap.add_argument("--train-days", type=int, default=28)
    ap.add_argument("--test-days", type=int, default=7)
    args = ap.parse_args(argv)

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, week_start, strategy, pnl_gbp, pct_of_perfect, regime FROM backtest_results "
            "WHERE strategy = 'tempo' AND run_id = COALESCE(%s, "
            "(SELECT max(run_id) FROM backtest_results WHERE strategy = 'tempo'))",
            (args.run_id,),
        )
        results = pd.DataFrame(
            cur.fetchall(),
            columns=["run_id", "week_start", "strategy", "pnl_gbp", "pct_of_perfect", "regime"],
        )
    if results.empty:
        raise SystemExit(
            "no tempo rows in backtest_results: run scripts/backtest.py --source db --write first"
        )
    results[["pnl_gbp", "pct_of_perfect"]] = results[["pnl_gbp", "pct_of_perfect"]].astype(float)
    row = pick_week(results)
    run_id = results.run_id.iloc[0]
    print(f"run {run_id}: windy week {row.week_start}, tempo {row.pct_of_perfect:.1f}% of perfect")

    prices_hh, _, frames = load_db(conn)
    start, end = prices_hh.bucket.min().ceil("D"), prices_hh.bucket.max().floor("D")
    window = next(
        (
            w
            for w in make_windows(start, end, args.train_days, args.test_days)
            if w.test_start.date() == row.week_start
        ),
        None,
    )
    if window is None:
        raise SystemExit(f"week {row.week_start} is not a test window of the current data")
    week = replay_week(prices_hh, window, TempoModel(frames))

    final, expected = week.cum_pnl_gbp.iloc[-1], row.pnl_gbp
    if abs(final - expected) > 0.005:
        raise SystemExit(
            f"rebuilt week makes {final:.2f} GBP but {run_id} recorded {expected:.2f}: not writing"
        )

    OUT.parent.mkdir(exist_ok=True)
    week.to_parquet(OUT, index=False)
    meta = {
        "run_id": run_id,
        "week_start": str(row.week_start),
        "regime": row.regime,
        "strategy": "tempo",
        "pct_of_perfect": round(row.pct_of_perfect, 1),
        "pnl_gbp": round(expected, 2),
        "chosen_as": "median windy week for tempo in this run",
        "rows": len(week),
    }
    OUT.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(week)} rows), final PnL {final:.2f} GBP matches the backtest")
    return week


if __name__ == "__main__":
    main()
