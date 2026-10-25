#!/usr/bin/env python3
"""How the live p10-p90 band would have done with conformal recalibration. Read-only against Tiger.

    .venv/bin/python scripts/calibration_report.py               # live forecasts on TEMPO_DATABASE_URL
    .venv/bin/python scripts/calibration_report.py --lookback 3  # recalibrate on the previous 3 days

Takes every settled forecast with run_id 'live', and for each batch widens its band by the offset from the
batches before it whose actual prices were already published at its decided_at (tempo/forecast/calibrate.py).
So each batch is recalibrated only on what Tempo could have known when it made it. Prints raw and
recalibrated coverage over the batches that had enough history. Nothing is written: the session is
read-only, and the live decider is untouched.
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tempo.features.build import mid_delay_min  # noqa: E402
from tempo.forecast.calibrate import rolling_offsets, widen  # noqa: E402

SQL = """
SELECT f.decided_at, f.target_time, f.p10, f.p50, f.p90, p.price AS actual
FROM forecasts f JOIN prices_hh p ON p.bucket = f.target_time
WHERE f.run_id = 'live'
ORDER BY f.decided_at, f.target_time
"""


def report(rows: pd.DataFrame, lookback_days: float) -> dict:
    delay = pd.Timedelta(minutes=30 + mid_delay_min())
    offsets = rolling_offsets(rows, lambda t: t + delay, pd.Timedelta(days=lookback_days))
    rows = rows.assign(offset=rows.decided_at.map(offsets)).dropna(subset=["offset"])
    if rows.empty:
        return {"rows": 0}
    cal = widen(rows[["p10", "p50", "p90"]], rows.offset)
    inside = lambda lo, hi: float(((rows.actual >= lo) & (rows.actual <= hi)).mean())  # noqa: E731
    return {
        "rows": len(rows),
        "batches": rows.decided_at.nunique(),
        "raw": inside(rows.p10, rows.p90),
        "recalibrated": inside(cal.p10, cal.p90),
        "median_offset": float(rows.offset.median()),
        "raw_width": float((rows.p90 - rows.p10).mean()),
        "recalibrated_width": float((cal.p90 - cal.p10).mean()),
        "first": rows.decided_at.min(),
        "last": rows.decided_at.max(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lookback", type=float, default=2.0, help="days of settled forecasts to recalibrate on")
    args = ap.parse_args(argv)

    import psycopg
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = os.environ.get("TEMPO_DATABASE_URL", "")
    if not url or "<password>" in url:
        print("TEMPO_DATABASE_URL is not set in .env")
        return 2
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        rows = pd.DataFrame(
            conn.execute(SQL).fetchall(), columns=["decided_at", "target_time", "p10", "p50", "p90", "actual"]
        )
    for c in ("decided_at", "target_time"):
        rows[c] = pd.to_datetime(rows[c], utc=True)
    for c in ("p10", "p50", "p90", "actual"):
        rows[c] = rows[c].astype(float)

    r = report(rows, args.lookback)
    print(f"{len(rows):,} settled live forecast half-hours in {rows.decided_at.nunique()} batches")
    if not r["rows"]:
        print(f"none had {args.lookback:g} days of settled history before them yet")
        return 0
    print(
        f"recalibrated on the previous {args.lookback:g} days: "
        f"{r['rows']:,} half-hours in {r['batches']} batches, "
        f"{r['first']:%d %b %H:%M} to {r['last']:%d %b %H:%M} UTC (target 80%)\n"
        f"  raw           {100 * r['raw']:.1f}% inside, mean width £{r['raw_width']:.1f}/MWh\n"
        f"  recalibrated  {100 * r['recalibrated']:.1f}% inside, "
        f"mean width £{r['recalibrated_width']:.1f}/MWh "
        f"(median offset £{r['median_offset']:.1f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
