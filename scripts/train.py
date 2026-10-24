#!/usr/bin/env python3
"""Train the LightGBM quantile forecaster on the last N days of prices and save it for run_decision.

    .venv/bin/python scripts/train.py                     # last 90 days on Tiger -> models/lgbm_*.joblib
    .venv/bin/python scripts/train.py --days 30 --every 12
    .venv/bin/python scripts/train.py --db local          # the local Docker DB
    .venv/bin/python scripts/train.py --out /opt/tempo/models
    .venv/bin/python scripts/train.py --until 2026-10-21T18:00:00Z --out models/pre21  # back-dated batches

Owner: Ernqi (Part A, docs/a.md item 2), written by Ayo.

Decision times every `--every` hours over the window; features through make_training_set, so nothing in X
is later than its decision time. The last `--holdout-days` of decision times are held out once to report
p50 MAE against persistence (price_lag_1d) and p10-p90 coverage on unseen rows, then the model is refitted
on everything and saved. models/ is gitignored: scripts/create_backend.py --deploy copies the three files
to /opt/tempo/models on the backend box.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.config import REPO_ROOT, settings  # noqa: E402
from tempo.features.build import mid_delay_min  # noqa: E402
from tempo.forecast.dataset import decision_times, first_usable_decision_time, make_training_set  # noqa: E402
from tempo.forecast.lgbm import LightGBMQuantileForecaster  # noqa: E402

log = logging.getLogger("train")
DEFAULT_OUT = REPO_ROOT / "models"


def holdout_report(X: pd.DataFrame, y: pd.Series, holdout_days: int, **params) -> dict | None:
    """Fit on the earlier decision times, score the last `holdout_days` of decision times."""
    dts = X.index.get_level_values("decision_time")
    cut = dts.max() - pd.Timedelta(days=holdout_days)
    train, test = dts <= cut, (dts > cut) & y.notna().to_numpy()
    if train.sum() < 48 or test.sum() < 48:
        return None
    model = LightGBMQuantileForecaster(**params)
    model.fit(X[train], y[train])
    pred = model.predict(X[test])
    yt = y[test].to_numpy()
    return {
        "holdout_rows": int(test.sum()),
        "p50_mae": float(np.mean(np.abs(pred.p50.to_numpy() - yt))),
        "persistence_mae": float(np.mean(np.abs(X.loc[test, "price_lag_1d"].to_numpy() - yt))),
        "band_coverage": float(np.mean((yt >= pred.p10.to_numpy()) & (yt <= pred.p90.to_numpy()))),
    }


def train(
    conn, *, days: int, every_h: int, out: Path, holdout_days: int = 7, until=None, **params
) -> dict:
    """until (optional): train only on prices published by then, for a model that may make decisions dated
    from `until` on without having seen their outcomes."""
    t0 = time.monotonic()
    latest = conn.execute("SELECT max(bucket) FROM prices_hh").fetchone()[0]
    if latest is None:
        raise SystemExit("prices_hh is empty: run the backfill first")
    end = pd.Timestamp(latest).tz_convert("UTC").floor("6h") - pd.Timedelta(
        hours=24
    )  # targets mostly settled
    if until is not None:
        # The last target starts 24 h after the last decision and is published 30 min + MID delay later.
        publish_lag = pd.Timedelta(hours=24, minutes=30 + mid_delay_min())
        end = min(end, (pd.Timestamp(until).tz_convert("UTC") - publish_lag).floor("6h"))
    start = end - pd.Timedelta(days=days)
    earliest = first_usable_decision_time(conn)
    if earliest is not None and pd.Timestamp(earliest) > start:
        log.info("window start moved from %s to %s (needs 8 days of history)", start, earliest)
        start = pd.Timestamp(earliest)
    times = decision_times(start.to_pydatetime(), end.to_pydatetime(), timedelta(hours=every_h))
    log.info("building features for %d decision times, %s to %s", len(times), start, end)
    X, y = make_training_set(conn, times, strict=False)
    log.info(
        "training set: %d rows (%d with a realised price) in %.0fs",
        len(X),
        int(y.notna().sum()),
        time.monotonic() - t0,
    )

    report = holdout_report(X, y, holdout_days, **params)
    model = LightGBMQuantileForecaster(**params)
    model.fit(X, y)
    paths = model.save(out)
    meta = {
        "trained_at": pd.Timestamp.now("UTC").isoformat(),
        "decision_times": len(times),
        "window": [str(times[0]), str(times[-1])],
        "every_h": every_h,
        "until": None if until is None else str(pd.Timestamp(until).tz_convert("UTC")),
        "rows": int(len(X)),
        "rows_with_price": int(y.notna().sum()),
        "features": model.features,
        "holdout": report,
        "seconds": round(time.monotonic() - t0, 1),
        "files": [str(p) for p in paths],
    }
    (Path(out) / "training.json").write_text(json.dumps(meta, indent=2))
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--every", type=int, default=6, help="hours between decision times")
    ap.add_argument("--holdout-days", type=int, default=7)
    ap.add_argument(
        "--db", default=None, help="'local' for the Docker DB, or a DSN; default TEMPO_DATABASE_URL"
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--until", help="train only on prices published by this time (ISO 8601 with timezone)")
    args = ap.parse_args(argv)
    until = pd.Timestamp(args.until) if args.until else None
    if until is not None and until.tzinfo is None:
        print("--until needs a timezone, e.g. 2026-10-21T18:00:00Z")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import psycopg

    s = settings()
    url = s.test_database_url if args.db == "local" else (args.db or s.database_url)
    if not url:
        print("no database: set TEMPO_DATABASE_URL or pass --db")
        return 2
    with psycopg.connect(url, autocommit=True) as conn:
        meta = train(
            conn,
            days=args.days,
            every_h=args.every,
            out=args.out,
            holdout_days=args.holdout_days,
            until=until,
        )
    h = meta["holdout"]
    print(f"saved {len(meta['files'])} files to {args.out} ({meta['rows']} rows, {meta['seconds']}s)")
    if h:
        print(
            f"holdout {h['holdout_rows']} rows: p50 MAE {h['p50_mae']:.2f} "
            f"vs persistence {h['persistence_mae']:.2f}, "
            f"p10-p90 coverage {100 * h['band_coverage']:.0f}% (target 80%)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
