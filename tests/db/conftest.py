"""Helpers for DB tests that need decisions and actual prices.

`prices_hh` is Girik's continuous aggregate and does not exist yet; tests create a TEMP table of the same
name and shape. Postgres resolves temp relations first, so this shadows the real aggregate when it lands
and the tests keep working unchanged.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from tempo.audit.refsim import Battery, simulate

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
PERIOD = timedelta(minutes=30)


def targets(decided_at=T0, n=48):
    return [decided_at + PERIOD * (k + 1) for k in range(n)]


@pytest.fixture
def market(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE IF NOT EXISTS prices_hh "
            "(bucket timestamptz PRIMARY KEY, price double precision, volume double precision)"
        )
        cur.execute("TRUNCATE pg_temp.prices_hh")
    return Market(db_conn)


class Market:
    def __init__(self, conn):
        self.conn = conn

    def prices(self, times, prices):
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO prices_hh (bucket, price, volume) VALUES (%s, %s, 100) "
                "ON CONFLICT (bucket) DO UPDATE SET price = EXCLUDED.price",
                [(t, float(p)) for t, p in zip(times, prices, strict=True)],
            )

    def decisions(self, mw, decided_at=T0, run_id="live"):
        """Insert one 48-row decision batch; return the decision_id of the first period."""
        ids = []
        with self.conn.cursor() as cur:
            for t, m in zip(targets(decided_at, len(mw)), mw, strict=True):
                action = "charge" if m > 0 else "discharge" if m < 0 else "hold"
                cur.execute(
                    "INSERT INTO decisions (decided_at, target_time, action, mw, reason, run_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING decision_id",
                    (decided_at, t, action, float(m), "test" if action == "hold" else None, run_id),
                )
                ids.append(cur.fetchone()[0])
        return ids[0]

    def start_soc(self, soc, run_id="live", ts=T0):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO battery_state (ts, soc_mwh, cum_pnl_gbp, run_id) VALUES (%s, %s, 0, %s)",
                (ts, soc, run_id),
            )

    def state(self, run_id):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT ts, soc_mwh, cum_pnl_gbp FROM battery_state WHERE run_id = %s ORDER BY ts", (run_id,)
            )
            return cur.fetchall()


def day_prices(seed=0):
    """Cheap night, dear evening, noise. Deterministic."""
    rng = np.random.default_rng(seed)
    hours = np.array([(t.hour + t.minute / 60) for t in targets()])
    return 60 - 30 * ((hours >= 1) & (hours < 5)) + 40 * ((hours >= 17) & (hours < 19)) + rng.normal(0, 5, 48)


def direct_pnl(mw, prices, soc=1.0):
    return simulate(Battery(soc_mwh=soc), np.asarray(mw, float), np.asarray(prices, float)).pnl_gbp
