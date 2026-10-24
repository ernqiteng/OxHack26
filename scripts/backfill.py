"""Two-year Elexon backfill into grid_raw. Owner: Girik.

python scripts/backfill.py                      # all datasets, 730 days, DB from TEMPO_DATABASE_URL
python scripts/backfill.py --db local           # local Docker DB
python scripts/backfill.py --datasets MID INDO --days 30
python scripts/backfill.py --no-resume          # reload every window (upsert keeps it idempotent)
python scripts/backfill.py --max-storage-mb 600 # abort before the Tiger free service goes read-only
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv

from tempo.db.conn import get_conn
from tempo.ingest.backfill import DEFAULT_ORDER, backfill, lookahead_check
from tempo.ingest.elexon import ElexonClient

LOCAL_URL = "postgres://postgres:tempo@localhost:5433/postgres"


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="env", help="'env' (TEMPO_DATABASE_URL), 'local' (Docker), or a DSN")
    p.add_argument("--datasets", nargs="+", default=list(DEFAULT_ORDER), choices=list(DEFAULT_ORDER))
    p.add_argument("--days", type=int, default=730)
    p.add_argument("--end", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC), default=None)
    p.add_argument("--window-days", type=int, default=None, help="override per-dataset window (default 60)")
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--no-compress", action="store_true")
    p.add_argument("--max-storage-mb", type=float, default=None)
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise for 730 DISEBSP days
    url = None if a.db == "env" else LOCAL_URL if a.db == "local" else a.db
    with get_conn(url) as conn:
        reports = backfill(
            conn,
            ElexonClient(),
            datasets=tuple(a.datasets),
            days=a.days,
            end=a.end,
            window_days=a.window_days,
            resume=not a.no_resume,
            compress=not a.no_compress,
            max_storage_mb=a.max_storage_mb,
            report=logging.info,
        )
        total = sum(r.rows_inserted for r in reports)
        leaks = lookahead_check(conn)
        bad = [r for r in reports if r.coverage is None or not r.coverage.ok]
        logging.info("done: %d new rows; non-forecast rows with available_at > now(): %d", total, leaks)
        for r in bad:
            logging.error("COVERAGE PROBLEM %s", r.coverage.summary() if r.coverage else r.dataset)
        if leaks:
            return 1
        return 2 if bad else 0  # a silent half-load is the worst failure mode: make it loud


if __name__ == "__main__":
    raise SystemExit(main())
