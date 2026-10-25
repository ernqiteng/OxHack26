"""Walk-forward backtest of every strategy, tempo and tempo_lp included. Prints the honesty table.

Owner: Ernqi. See docs/ernqi.md Phase 1 task 7.

    python scripts/backtest.py                      # Tiger prices_hh if it has data, else synthetic
    python scripts/backtest.py --source synthetic   # 60-day synthetic market (tests/fixtures/synthetic.py)
    python scripts/backtest.py --source db --write  # also insert rows into backtest_results
    python scripts/backtest.py --no-tempo           # skip tempo / tempo_lp (minutes faster)
    python scripts/backtest.py --source db --calibration   # + band raw vs recalibrated, conservative LP

Reads TEMPO_DATABASE_URL from .env. --write needs a run_id not used before ((run_id, week_start, strategy)
is the primary key); the default run_id includes the time, so plain re-runs never collide.
Synthetic results are never written: they would sit in the shared table next to real ones.
tempo and tempo_lp retrain LightGBM per window on its train days, with features from build_features
answered in memory (tempo/backtest/features.py): every WINDFOR/NDF publication is loaded once.
--calibration is an experiment and can't be combined with --write: the dashboard and the pitch site read
the newest run_id in backtest_results, so its extra strategies would replace what they show.
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tempo.backtest.metrics import summary  # noqa: E402
from tempo.backtest.walkforward import (  # noqa: E402
    STRATEGIES,
    TempoModel,
    band_check,
    band_coverage,
    make_windows,
    prices_hh_from_grid_raw,
    run_all,
    run_strategy,
    tempo_strategies,
    weekly_regimes,
    write_results,
)


def connect():
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = os.environ.get("TEMPO_DATABASE_URL", "")
    if not url or "<password>" in url:
        raise SystemExit("TEMPO_DATABASE_URL is not set in .env")
    return psycopg.connect(url, autocommit=True)


def load_db(conn):
    """prices_hh, the WINDFOR/NDF publications (regimes), and the frames tempo's features are built from."""
    from tempo.backtest.features import load_frames

    frames = load_frames(conn)
    prices_hh = pd.DataFrame({"bucket": frames.prices.index, "price": frames.prices.to_numpy()})
    grid = frames.forecasts
    return prices_hh, (grid if "WINDFOR" in set(grid.dataset) else None), frames


def load_synthetic():
    from tempo.backtest.features import frames_from_grid
    from tests.fixtures.synthetic import make_synthetic_market

    grid = make_synthetic_market()
    return prices_hh_from_grid_raw(grid), grid, frames_from_grid(grid)


def run_with_calibration(prices_hh, grid, windows, run_id, frames):
    """Every default strategy, then the band check on the same fits, then the conservative LP (buy at p90,
    sell at p10) on the raw and on the recalibrated band."""
    from tempo.optimise.lp import LPOptimiser

    model = TempoModel(frames)
    results = run_all(
        prices_hh, grid, windows, run_id, strategies={**STRATEGIES, **tempo_strategies(frames, model=model)}
    )
    band = band_check(model, prices_hh, windows)
    regimes = weekly_regimes(grid, windows) if grid is not None else {}
    extra = {
        "tempo_lp_safe": model.strategy(LPOptimiser(conservative=True)),
        "tempo_lp_safe_cal": model.strategy(LPOptimiser(conservative=True), calibrated=True),
    }
    rows = [
        r
        for name, fn in extra.items()
        for r in run_strategy(name, prices_hh, windows, fn, run_id, regimes=regimes)
    ]
    return pd.concat([results, pd.DataFrame(rows)], ignore_index=True), band


def print_band(band):
    c = band_coverage(band)
    if not c["rows"]:
        print("\nBand: no test day had enough settled history to recalibrate")
        return
    print(
        f"\nBand p10-p90 on {c['rows']:,} unseen half-hours (target 80%)\n"
        f"  raw           {100 * c['raw']:.1f}% inside, mean width £{c['raw_width']:.1f}/MWh\n"
        f"  recalibrated  {100 * c['recalibrated']:.1f}% inside, "
        f"mean width £{c['recalibrated_width']:.1f}/MWh "
        f"(median offset £{c['median_offset']:.1f}, from the previous 7 days' settled forecasts)"
    )
    b = band.dropna(subset=["offset"])
    weekly = (
        b.assign(
            raw=(b.actual >= b.p10) & (b.actual <= b.p90),
            cal=(b.actual >= b.p10_cal) & (b.actual <= b.p90_cal),
        )
        .groupby("week_start")[["raw", "cal"]]
        .mean()
    )
    print(
        f"  weeks within 70-90%: raw {weekly.raw.between(0.7, 0.9).sum()} of {len(weekly)}, "
        f"recalibrated {weekly.cal.between(0.7, 0.9).sum()} of {len(weekly)}"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["auto", "db", "synthetic"], default="auto")
    ap.add_argument("--run-id")
    ap.add_argument("--train-days", type=int, default=28)
    ap.add_argument("--test-days", type=int, default=7)
    ap.add_argument("--write", action="store_true", help="insert rows into backtest_results (db source only)")
    ap.add_argument("--no-tempo", action="store_true", help="skip tempo / tempo_lp (no LightGBM training)")
    ap.add_argument(
        "--calibration",
        action="store_true",
        help="also check the band raw and recalibrated, and run the conservative LP on each (never written)",
    )
    args = ap.parse_args(argv)
    if args.calibration and (args.write or args.no_tempo):
        raise SystemExit("--calibration can't be combined with --write or --no-tempo")

    source, conn = args.source, None
    if source in ("auto", "db"):
        try:
            conn = connect()
            prices_hh, grid, frames = load_db(conn)
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
        prices_hh, grid, frames = load_synthetic()
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
        f"{source}: {len(prices_hh)} half-hours, {start.date()} to {end.date()}, "
        f"{len(windows)} test weeks, run_id {run_id}"
    )

    band = None
    if args.calibration:
        results, band = run_with_calibration(prices_hh, grid, windows, run_id, frames)
    else:
        results = run_all(prices_hh, grid, windows, run_id, frames=None if args.no_tempo else frames)
    weekly = results.pivot(index=["week_start", "regime"], columns="strategy", values="pct_of_perfect")
    print("\n% of perfect by week\n" + weekly.round(1).to_string())
    table = summary(results)
    print(
        "\nHonesty table\n"
        + table.drop(columns="strategy").to_string(index=False, float_format=lambda x: f"{x:,.1f}")
    )

    if band is not None:
        print_band(band)

    worst = results[results.pct_of_perfect > 100 + 1e-6]
    if len(worst):
        print(
            f"\nWARNING: {len(worst)} week(s) beat perfect foresight. "
            "That is a lookahead leak, find it before trusting this."
        )

    if args.write:
        print(f"\nwrote {write_results(conn, results)} rows to backtest_results")
    return results


if __name__ == "__main__":
    main()
