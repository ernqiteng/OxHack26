#!/usr/bin/env python3
"""Seed (or remove) a rehearsal decision batch so the fork audit can be clicked on the dashboard before the
live decision engine exists. Writes decisions only (run_id 'selftest'), against prices already on Tiger;
never touches grid_raw or the aggregates. Labelled "[rehearsal]" in the dashboard; demo_reset warns while
the rows exist.

    .venv/bin/python scripts/seed_selftest.py           # seed on TEMPO_DATABASE_URL, print the decision_id
    .venv/bin/python scripts/seed_selftest.py --remove  # delete the rows, their audits and battery_state
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.audit import rehearsal  # noqa: E402
from tempo.config import settings  # noqa: E402


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
            print(f"removed {rehearsal.remove(conn)} rehearsal decision rows")
        else:
            did = rehearsal.seed(conn)
            when = conn.execute("SELECT decided_at FROM decisions WHERE decision_id = %s", (did,)).fetchone()[
                0
            ]
            print(
                f"rehearsal batch seeded for {when:%Y-%m-%d %H:%M} UTC: click decision #{did} ([rehearsal])"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
