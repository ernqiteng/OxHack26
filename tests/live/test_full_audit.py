"""One real fork-mode audit on Tiger (docs/ayo.md Phase 2): fork at click time, five workers, five numbers,
no forks left behind, under 180 s, equal to the in-process replay. Needs TEMPO_LIVE=1 and Tiger creds.

The free tier allows 2 services per project (primary + 1 fork), so this audits the primary itself with the
'shared' layout. It writes only a rehearsal decision batch (run_id 'selftest', tempo.audit.rehearsal)
against prices already on Tiger, and removes it with its audits and battery_state rows in `finally`.
It runs the audit twice back to back, because a presenter may click twice.
"""

import time

import psycopg
import pytest

from tempo.audit import rehearsal
from tempo.audit.orchestrator import AuditProgress, check_audit_rows, run_audit
from tempo.audit.pool import default_pool
from tempo.config import settings
from tempo.infra.tiger import TigerClient

pytestmark = pytest.mark.live


def seed(conn) -> int:
    return rehearsal.seed(conn)


def cleanup(conn, did: int | None) -> None:
    rehearsal.remove(conn)


def one_audit(conn, tiger, pool, did, label):
    progress = AuditProgress()
    t0 = time.monotonic()
    rows = run_audit(conn, did, mode="fork", tiger=tiger, pool=pool, forks="shared", progress=progress)
    elapsed = time.monotonic() - t0
    print(f"\n--- {label}: {elapsed:.1f}s")
    print("\n".join(progress.log_lines()))
    return rows, elapsed, progress


def test_full_fork_audit_on_tiger():
    s = settings()
    if not s.tiger.configured or not s.tiger.primary_service_id or not s.database_url:
        pytest.skip("Tiger credentials, TIGER_PRIMARY_SERVICE_ID or TEMPO_DATABASE_URL missing")
    tiger = TigerClient.from_env()
    did = None
    with psycopg.connect(s.database_url, autocommit=True) as conn:
        try:
            cleanup(conn, None)  # in case a previous run died before its finally
            did = seed(conn)
            pool, note = default_pool()
            print(f"\nworkers: {note}")

            rows, elapsed, progress = one_audit(conn, tiger, pool, did, "audit 1")
            check_audit_rows(rows)
            assert [r.error for r in rows] == [None] * 5, progress.log_lines()
            assert elapsed < 180

            stored = conn.execute(
                "SELECT shift, mode FROM audits WHERE decision_id = %s ORDER BY shift", (did,)
            ).fetchall()
            assert stored == [(sh, "fork") for sh in (-2, -1, 0, 1, 2)]
            leaked = conn.execute(
                "SELECT count(*) FROM battery_state WHERE run_id LIKE %s", (f"audit-{did}-%",)
            ).fetchone()[0]
            assert leaked == 0, "fork replays must write into the fork, never the primary"
            assert [x.name for x in tiger.list_services() if x.name.startswith("audit-")] == []

            rows2, elapsed2, progress2 = one_audit(conn, tiger, pool, did, "audit 2 (immediate re-click)")
            assert [r.error for r in rows2] == [None] * 5, progress2.log_lines()
            assert [round(r.pnl_gbp, 2) for r in rows2] == [round(r.pnl_gbp, 2) for r in rows]

            inproc = run_audit(conn, did, mode="inprocess", write=False)
            for f, i in zip(rows, inproc, strict=True):
                assert round(f.pnl_gbp, 2) == round(i.pnl_gbp, 2), (f.shift, f.pnl_gbp, i.pnl_gbp)
            print("\nshift   fork £   in-process £   worker")
            for f, i in zip(rows, inproc, strict=True):
                print(f"{f.shift:+5d} {f.pnl_gbp:9.2f} {i.pnl_gbp:13.2f}   {f.worker_id}")
        finally:
            cleanup(conn, did)
            assert [x.name for x in tiger.list_services() if x.name.startswith("audit-")] == []
            tiger.close()
