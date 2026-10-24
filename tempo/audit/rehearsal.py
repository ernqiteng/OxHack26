"""Rehearsal decision batch: lets the fork audit be clicked before the live decision engine exists.

Owner: Ayo. Writes ONLY `decisions` rows under run_id 'selftest', against prices that are already in
`prices_hh` (a full day about three days before the newest price), so nothing touches grid_raw or the
aggregates. The dashboard labels the batch "[rehearsal]"; demo_reset warns while it exists; `remove()`
deletes it with its audits and battery_state rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

RUN_ID = "selftest"
PERIOD = timedelta(minutes=30)


def pick_decided_at(conn) -> datetime | None:
    """A 12:00 UTC decision time whose next 48 periods all have prices, about three days back."""
    latest = conn.execute("SELECT max(bucket) FROM prices_hh").fetchone()[0]
    if latest is None:
        return None
    candidate = (latest - timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
    for _ in range(10):
        n = conn.execute(
            "SELECT count(*) FROM prices_hh WHERE bucket > %s AND bucket <= %s AND price IS NOT NULL",
            (candidate, candidate + PERIOD * 48),
        ).fetchone()[0]
        if n == 48:
            return candidate
        candidate -= timedelta(days=1)
    return None


def seed(conn) -> int:
    """Insert the batch and return the decision_id of its first charge (what the dashboard should show)."""
    remove(conn)
    decided_at = pick_decided_at(conn)
    if decided_at is None:
        raise RuntimeError("no day with 48 consecutive prices in prices_hh; run the backfill first")
    rows = conn.execute(
        "SELECT bucket, price FROM prices_hh WHERE bucket > %s AND bucket <= %s ORDER BY bucket",
        (decided_at, decided_at + PERIOD * 48),
    ).fetchall()
    targets = [r[0] for r in rows]
    prices = np.array([float(r[1]) for r in rows])
    # Charge the four cheapest periods, sell the four dearest periods that come after them.
    cheap = np.argsort(prices)[:4]
    after = max(cheap) + 1
    dear = after + np.argsort(prices[after:])[-4:] if after < 44 else np.argsort(prices)[-4:]
    mw = np.zeros(48)
    mw[cheap], mw[dear] = 1.0, -1.0
    ids = []
    with conn.cursor() as cur:
        for t, m in zip(targets, mw, strict=True):
            action = "charge" if m > 0 else "discharge" if m < 0 else "hold"
            reason = "rehearsal hold: spread below cost" if action == "hold" else None
            cur.execute(
                "INSERT INTO decisions (decided_at, target_time, action, mw, reason, run_id) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING decision_id",
                (decided_at, t, action, float(m), reason, RUN_ID),
            )
            ids.append(cur.fetchone()[0])
    return ids[int(min(cheap))]


def remove(conn) -> int:
    ids = [r[0] for r in conn.execute("SELECT decision_id FROM decisions WHERE run_id = %s", (RUN_ID,))]
    conn.execute("DELETE FROM decisions WHERE run_id = %s", (RUN_ID,))
    for did in ids:
        conn.execute("DELETE FROM audits WHERE decision_id = %s", (did,))
        conn.execute("DELETE FROM battery_state WHERE run_id LIKE %s", (f"audit-{did}-%",))
    return len(ids)
