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
