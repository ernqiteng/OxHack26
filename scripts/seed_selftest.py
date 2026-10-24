#!/usr/bin/env python3
"""Seed (or remove) a rehearsal decision batch so the fork audit can be clicked on the dashboard before the
live decision engine exists. Rows are run_id 'selftest', dated 1 January 2001 (prices through grid_raw, so
prices_hh is the real aggregate), labelled "[rehearsal]" in the dashboard and ignored by demo_reset's
candidate picker, which warns while they exist.

    .venv/bin/python scripts/seed_selftest.py           # seed on TEMPO_DATABASE_URL, print the decision_id
    .venv/bin/python scripts/seed_selftest.py --remove  # delete the rows, their audits and battery_state
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.config import settings  # noqa: E402

T0 = datetime(2001, 1, 1, 12, 0, tzinfo=UTC)
PERIOD = timedelta(minutes=30)
WINDOW = (T0 - timedelta(days=1), T0 + timedelta(days=2))
RUN_ID = "selftest"


def refresh(conn) -> None:
    conn.execute("CALL refresh_continuous_aggregate('prices_hh', %s, %s)", WINDOW)


def seed(conn) -> int:
    targets = [T0 + PERIOD * (k + 1) for k in range(48)]
    hours = np.array([t.hour + t.minute / 60 for t in targets])
    prices = 60 - 30 * ((hours >= 1) & (hours < 5)) + 40 * ((hours >= 17) & (hours < 19))
    mw = np.zeros(48)
    mw[[26, 27, 28, 29]] = 1.0  # charge 01:00-03:00 UTC, the cheap window
    mw[[9, 10]] = -1.0  # sell 17:00-18:00 UTC, the dear window
    rows = [(t, t + timedelta(minutes=40), "APXMIDP", float(p)) for t, p in zip(targets, prices, strict=True)]
    rows += [(t, t + timedelta(minutes=40), "APXMIDP:volume", 500.0) for t in targets]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO grid_raw (start_time, available_at, dataset, series, value) "
            "VALUES (%s, %s, 'MID', %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )
        ids = []
        for t, m in zip(targets, mw, strict=True):
            action = "charge" if m > 0 else "discharge" if m < 0 else "hold"
            reason = "rehearsal hold: spread 4.0 < cost 18.0" if action == "hold" else None
            cur.execute(
                "INSERT INTO decisions (decided_at, target_time, action, mw, reason, run_id) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING decision_id",
                (T0, t, action, float(m), reason, RUN_ID),
            )
            ids.append(cur.fetchone()[0])
    refresh(conn)
    n = conn.execute("SELECT count(*) FROM prices_hh WHERE bucket > %s AND bucket < %s", WINDOW).fetchone()[0]
    assert n == 48, f"prices_hh shows {n} seeded periods, expected 48"
    return ids[26]  # the first charge, so the dashboard label reads 'charge'


def remove(conn) -> None:
    ids = [r[0] for r in conn.execute("SELECT decision_id FROM decisions WHERE run_id = %s", (RUN_ID,))]
    conn.execute("DELETE FROM decisions WHERE run_id = %s", (RUN_ID,))
    conn.execute("DELETE FROM grid_raw WHERE dataset = 'MID' AND start_time > %s AND start_time < %s", WINDOW)
    for did in ids:
        conn.execute("DELETE FROM audits WHERE decision_id = %s", (did,))
        conn.execute("DELETE FROM battery_state WHERE run_id LIKE %s", (f"audit-{did}-%",))
    refresh(conn)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    import psycopg

    url = settings().database_url
    if not url:
        print("TEMPO_DATABASE_URL missing")
        return 2
    with psycopg.connect(url, autocommit=True) as conn:
        if args.remove:
            remove(conn)
            print("rehearsal rows removed")
        else:
            remove(conn)  # idempotent
            did = seed(conn)
            print(f"rehearsal batch seeded: click decision #{did} in the dashboard (labelled [rehearsal])")
    return 0


if __name__ == "__main__":
    sys.exit(main())
