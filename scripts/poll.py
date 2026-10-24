"""Live Elexon poller into grid_raw. Owner: Girik.

    python scripts/poll.py                    # poll every 60 s forever, DB from TEMPO_DATABASE_URL (Tiger)
    python scripts/poll.py --once             # one cycle, then exit (catch up after downtime)
    python scripts/poll.py --db local         # local Docker DB
    python scripts/poll.py --lookback-days 5  # first cycle reaches further back (poller was off > 2 days)

Runs under deploy/systemd/tempo-poller.service on the backend box (no arguments). Logs one line per fetch
to stdout.
"""

import argparse
import logging
import sys
from datetime import timedelta

from dotenv import load_dotenv

from tempo.db.conn import get_conn, upsert_grid_raw
from tempo.ingest.elexon import ElexonClient
from tempo.ingest.poll import DEFAULT_DATASETS, Poller, assert_known

LOCAL_URL = "postgres://postgres:tempo@localhost:5433/postgres"


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="env", help="'env' (TEMPO_DATABASE_URL), 'local' (Docker), or a DSN")
    p.add_argument("--interval", type=float, default=60.0, help="seconds between metadata checks")
    p.add_argument("--lookback-days", type=float, default=2.0)
    p.add_argument("--datasets", nargs="+", default=list(DEFAULT_DATASETS))
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    assert_known(a.datasets)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    url = None if a.db == "env" else LOCAL_URL if a.db == "local" else a.db
    with get_conn(url) as conn:
        poller = Poller(
            ElexonClient(),
            sink=lambda df: upsert_grid_raw(conn, df),
            datasets=a.datasets,
            lookback=timedelta(days=a.lookback_days),
        )
        logging.info("poller started: %s every %.0fs, lookback %.1f days", ",".join(a.datasets), a.interval,
                     a.lookback_days)  # fmt: skip
        poller.run(interval_s=a.interval, iterations=1 if a.once else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
