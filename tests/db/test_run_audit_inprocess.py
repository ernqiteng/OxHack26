"""run_audit(mode='inprocess') writes five audits rows with consistent deltas."""

import numpy as np
import pytest

from tempo.audit.orchestrator import check_audit_rows, run_audit
from tempo.audit.shifts import replay_shift

from .conftest import day_prices, targets


def audits(conn, decision_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT shift, pnl_gbp, pnl_delta_gbp, mode, started_at, finished_at FROM audits "
            "WHERE decision_id = %s ORDER BY shift",
            (decision_id,),
        )
        return cur.fetchall()


def test_five_rows_written(market):
    mw = np.zeros(48)
    mw[2:6], mw[34:38] = 1.0, -1.0
    market.prices(targets(), day_prices())
    did = market.decisions(mw)

    rows = run_audit(market.conn, did)

    check_audit_rows(rows)
    stored = audits(market.conn, did)
    assert [r[0] for r in stored] == [-2, -1, 0, 1, 2]
    zero = stored[2]
    assert zero[2] == 0.0
    assert all(r[3] == "inprocess" for r in stored)
    assert all(r[5] >= r[4] for r in stored)
    for (_shift, pnl, delta, *_), row in zip(stored, rows, strict=True):
        assert pnl == pytest.approx(row.pnl_gbp)
        assert delta == pytest.approx(pnl - zero[1])
    # each shift wrote its own battery_state run
    for s in (-2, -1, 0, 1, 2):
        assert len(market.state(f"audit-{did}-{s}")) == 48


def test_one_failed_shift_still_writes_the_others(market):
    market.prices(targets(), day_prices())
    did = market.decisions(np.tile([1.0, 0.0, -1.0, 0.0], 12))

    def flaky(conn, decision_id, shift, run_id, **kw):
        if shift == 2:
            raise RuntimeError("worker died")
        return replay_shift(conn, decision_id, shift, run_id, **kw)

    rows = run_audit(market.conn, did, replay=flaky)

    check_audit_rows(rows)
    failed = [r for r in rows if r.failed]
    assert [r.shift for r in failed] == [2] and "worker died" in failed[0].error
    stored = audits(market.conn, did)
    assert stored[4][1] is None and stored[4][2] is None
    assert all(r[1] is not None for r in stored[:4])


def test_rerunning_an_audit_does_not_hit_battery_state_key(market):
    """battery_state's PRIMARY KEY (ts, run_id) rejects duplicates; a retry must clear and rewrite."""
    market.prices(targets(), day_prices())
    did = market.decisions(np.tile([1.0, 0.0, -1.0, 0.0], 12))

    first = run_audit(market.conn, did)
    second = run_audit(market.conn, did)

    assert [r.pnl_gbp for r in first] == [r.pnl_gbp for r in second]
    assert all(r.error is None for r in second)
    for s in (-2, -1, 0, 1, 2):
        assert len(market.state(f"audit-{did}-{s}")) == 48
    assert len(audits(market.conn, did)) == 10  # audits keeps history; one set per run


def test_second_writer_between_delete_and_insert_does_not_collide(market):
    """Two dashboard viewers run the self-grade at once under the same run ids. Viewer B's rows can land
    between viewer A's DELETE and INSERT; A's insert must then update them, not fail on the primary key."""
    from tempo.audit.shifts import write_battery_state

    targets_ = targets()
    soc, cum = np.full(48, 1.0), np.arange(48, dtype=float)
    write_battery_state(market.conn, "selfgrade-race", targets_, soc, cum)  # viewer B finished first

    class SkipDelete:
        """Viewer A's connection, as seen after its DELETE already ran (B's rows are now present)."""

        def __init__(self, conn):
            self.conn = conn

        def cursor(self):
            real = self.conn.cursor()

            class Cur:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    real.close()

                def execute(self_inner, sql, params=None):
                    if sql.lstrip().upper().startswith("DELETE"):
                        return None
                    return real.execute(sql, params)

                def executemany(self_inner, sql, rows):
                    return real.executemany(sql, rows)

            return Cur()

    write_battery_state(SkipDelete(market.conn), "selfgrade-race", targets_, soc * 0.5, cum * 2)
    rows = market.state("selfgrade-race")
    assert len(rows) == 48
    assert rows[0][1] == 0.5 and rows[-1][2] == 94.0  # A's values won, no duplicate-key error
