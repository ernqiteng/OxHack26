"""One real fork-mode audit on Tiger (docs/ayo.md Phase 2): fork at click time, five workers, five numbers,
no forks left behind, under 180 s, equal to the in-process replay. Needs TEMPO_LIVE=1 and Tiger creds.

The free tier allows 2 services per project (primary + 1 fork), so this audits the primary itself with the
'shared' layout. To stay out of everyone's way it seeds only:
  - grid_raw MID rows dated 2001-01-01 (the 2-year backfill can never collide with them),
  - one decision batch under run_id 'selftest' (the dashboard shows run_id 'live' only),
and deletes all of it, plus its audits and battery_state rows, in `finally`.

It runs the audit twice back to back, because a presenter may click twice and the second fork needs the
first one's service slot to be free again.
"""

import time
from datetime import UTC, datetime, timedelta

import numpy as np
import psycopg
import pytest

from tempo.audit.orchestrator import AuditProgress, check_audit_rows, run_audit
from tempo.audit.pool import default_pool
from tempo.config import settings
from tempo.infra.tiger import TigerClient

pytestmark = pytest.mark.live

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
    mw[[26, 27, 28, 29]] = 1.0  # charge 01:00-03:00 UTC
    mw[[9, 10]] = -1.0  # sell 17:00-18:00 UTC
    rows = [(t, t + timedelta(minutes=40), "APXMIDP", float(p)) for t, p in zip(targets, prices, strict=True)]
    rows += [(t, t + timedelta(minutes=40), "APXMIDP:volume", 500.0) for t in targets]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO grid_raw (start_time, available_at, dataset, series, value) "
            "VALUES (%s, %s, 'MID', %s, %s)",
            rows,
        )
        ids = []
        for t, m in zip(targets, mw, strict=True):
            action = "charge" if m > 0 else "discharge" if m < 0 else "hold"
            cur.execute(
                "INSERT INTO decisions (decided_at, target_time, action, mw, reason, run_id) "
                "VALUES (%s, %s, %s, %s, 'selftest', %s) RETURNING decision_id",
                (T0, t, action, float(m), RUN_ID),
            )
            ids.append(cur.fetchone()[0])
    refresh(conn)
    n = conn.execute("SELECT count(*) FROM prices_hh WHERE bucket > %s AND bucket < %s", WINDOW).fetchone()[0]
    assert n == 48, f"prices_hh should expose the 48 seeded prices, got {n}"
    return ids[0]


def cleanup(conn, did: int | None) -> None:
    conn.execute("DELETE FROM decisions WHERE run_id = %s", (RUN_ID,))
    conn.execute("DELETE FROM grid_raw WHERE dataset = 'MID' AND start_time > %s AND start_time < %s", WINDOW)
    if did is not None:
        conn.execute("DELETE FROM audits WHERE decision_id = %s", (did,))
        conn.execute("DELETE FROM battery_state WHERE run_id LIKE %s", (f"audit-{did}-%",))
    refresh(conn)


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
