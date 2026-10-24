"""Walk-forward backtest: simple rule, persistence + greedy, perfect. Prints the honesty table.

Owner: Ernqi. See docs/ernqi.md Phase 1 task 7.

    python scripts/backtest.py                      # Tiger prices_hh if it has data, else synthetic
    python scripts/backtest.py --source synthetic   # 60-day synthetic market (tests/fixtures/synthetic.py)
    python scripts/backtest.py --source db --write  # also insert rows into backtest_results

Reads TEMPO_DATABASE_URL from .env. --write needs a run_id not used before ((run_id, week_start, strategy)
is the primary key); the default run_id includes the time, so plain re-runs never collide.
Synthetic results are never written: they would sit in the shared table next to real ones.
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tempo.backtest.metrics import summary  # noqa: E402
from tempo.backtest.walkforward import make_windows, prices_hh_from_grid_raw, run_all, write_results  # noqa: E402


def connect():
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = os.environ.get("TEMPO_DATABASE_URL", "")
    if not url or "<password>" in url:
        raise SystemExit("TEMPO_DATABASE_URL is not set in .env")
    return psycopg.connect(url, autocommit=True)


def load_db(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT bucket, price FROM prices_hh WHERE price IS NOT NULL ORDER BY bucket")
        prices_hh = pd.DataFrame(cur.fetchall(), columns=["bucket", "price"])
        cur.execute(
            """SELECT DISTINCT ON (dataset, start_time) start_time, available_at, dataset, value
               FROM grid_raw WHERE dataset IN ('WINDFOR', 'NDF')
               ORDER BY dataset, start_time, available_at DESC"""
        )
        grid = pd.DataFrame(cur.fetchall(), columns=["start_time", "available_at", "dataset", "value"])
    if len(prices_hh):
        prices_hh["bucket"] = pd.to_datetime(prices_hh.bucket, utc=True)
        prices_hh["price"] = prices_hh.price.astype(float)
    if len(grid):
        grid["start_time"] = pd.to_datetime(grid.start_time, utc=True)
        grid["available_at"] = pd.to_datetime(grid.available_at, utc=True)
        grid["value"] = grid.value.astype(float)
    return prices_hh, (grid if "WINDFOR" in set(grid.dataset) else None)


def load_synthetic():
    from tests.fixtures.synthetic import make_synthetic_market

    grid = make_synthetic_market()
    return prices_hh_from_grid_raw(grid), grid


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["auto", "db", "synthetic"], default="auto")
    ap.add_argument("--run-id")
    ap.add_argument("--train-days", type=int, default=28)
    ap.add_argument("--test-days", type=int, default=7)
    ap.add_argument("--write", action="store_true", help="insert rows into backtest_results (db source only)")
    args = ap.parse_args(argv)

    source, conn = args.source, None
    if source in ("auto", "db"):
        try:
            conn = connect()
            prices_hh, grid = load_db(conn)
        except Exception as exc:  # noqa: BLE001
            if source == "db":
                raise SystemExit(f"could not read prices_hh: {exc}") from exc
            prices_hh = pd.DataFrame()
            print(f"database not usable ({type(exc).__name__}), falling back to synthetic")
        if prices_hh.empty and source == "db":
            raise SystemExit("prices_hh has no rows yet: run the backfill first, or use --source synthetic")
        source = "db" if not prices_hh.empty else "synthetic"
        if source == "synthetic" and args.source == "auto":
            print("prices_hh is empty, using the synthetic market")
    if source == "synthetic":
        prices_hh, grid = load_synthetic()
    if args.write and source != "db":
        raise SystemExit("--write only works with real data (--source db)")

    start = prices_hh.bucket.min().ceil("D")
    end = prices_hh.bucket.max().floor("D")
    windows = list(make_windows(start, end, args.train_days, args.test_days))
    if not windows:
        raise SystemExit(
            f"not enough data: {start.date()} to {end.date()} is shorter than one train + test window"
        )
    run_id = args.run_id or f"{source}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    print(
        f"{source}: {len(prices_hh)} half-hours, {start.date()} to {end.date()}, {len(windows)} test weeks, run_id {run_id}"
    )

    results = run_all(prices_hh, grid, windows, run_id)
    weekly = results.pivot(index=["week_start", "regime"], columns="strategy", values="pct_of_perfect")
    print("\n% of perfect by week\n" + weekly.round(1).to_string())
    table = summary(results)
    print(
        "\nHonesty table\n"
        + table.drop(columns="strategy").to_string(index=False, float_format=lambda x: f"{x:,.1f}")
    )

    worst = results[results.pct_of_perfect > 100 + 1e-6]
    if len(worst):
        print(
            f"\nWARNING: {len(worst)} week(s) beat perfect foresight. That is a lookahead leak, find it before trusting this."
        )

    if args.write:
        print(f"\nwrote {write_results(conn, results)} rows to backtest_results")
    return results


if __name__ == "__main__":
    main()
