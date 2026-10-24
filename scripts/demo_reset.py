#!/usr/bin/env python3
"""Pre-demo go/no-go. Run before every rehearsal and before going on stage.

    .venv/bin/python scripts/demo_reset.py                 # check, delete stale audit forks, pick a decision
    .venv/bin/python scripts/demo_reset.py --dry-run       # check only, delete nothing
    .venv/bin/python scripts/demo_reset.py --decision 8812 # confirm the decision Ernqi gave you is replayable
    .venv/bin/python scripts/demo_reset.py --fork-test     # also take and delete one real fork (~40 s)
    .venv/bin/python scripts/demo_reset.py --no-score      # skip the in-process audits used to rank decisions

Exit code 0 means GO, 1 means NO-GO, 2 means it could not even start (missing credentials).
Scoring runs in-process audits, which write battery_state rows under audit-* run ids, never 'live'.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.audit.preflight import FREE_SERVICE_LIMIT, run_preflight  # noqa: E402
from tempo.config import env, settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report stale forks instead of deleting them")
    ap.add_argument("--decision", type=int, help="decision_id to confirm instead of auto-picking")
    ap.add_argument("--fork-test", action="store_true", help="take and delete one real fork and time it")
    ap.add_argument("--no-score", action="store_true", help="don't run in-process audits to rank decisions")
    args = ap.parse_args()

    s = settings()
    if not s.tiger.configured or not s.tiger.primary_service_id:
        print("missing TIGERDATA_* or TIGER_PRIMARY_SERVICE_ID in .env")
        return 2

    from tempo.audit.pool import default_pool
    from tempo.infra.tiger import TigerClient

    conn = None
    if s.database_url:
        try:
            import psycopg

            conn = psycopg.connect(s.database_url, connect_timeout=10, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            print(f"database connect failed: {exc}")
    try:
        pool, _ = default_pool()
    except Exception as exc:  # noqa: BLE001
        print(f"worker pool unavailable: {exc}")
        pool = None

    with TigerClient.from_env() as tiger:
        report = run_preflight(
            tiger=tiger,
            pool=pool,
            conn=conn,
            primary_id=s.tiger.primary_service_id,
            forks=s.audit_forks,
            dry_run=args.dry_run,
            decision_id=args.decision,
            score=not args.no_score,
            with_fork_test=args.fork_test,
            limit=int(env("TIGER_SERVICE_LIMIT", str(FREE_SERVICE_LIMIT))),
        )
    if conn is not None:
        conn.close()
    print("\n".join(report.lines()))
    return 0 if report.go else 1


if __name__ == "__main__":
    sys.exit(main())
