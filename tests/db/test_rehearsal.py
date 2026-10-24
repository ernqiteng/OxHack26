"""Rehearsal batch writes decisions only, against existing prices, and removes itself completely."""

import numpy as np

from tempo.audit import rehearsal
from tempo.audit.orchestrator import run_audit

from .conftest import T0, targets


def test_seed_uses_existing_prices_and_touches_nothing_else(market):
    from datetime import timedelta

    # four days of prices so a 12:00 decision three days before the newest has 48 priced periods
    for d in range(5):
        start = T0 - timedelta(days=4 - d)
        market.prices(targets(start - timedelta(hours=12)), 50 + 30 * np.sin(np.arange(48) / 7))
    before = market.conn.execute("SELECT count(*) FROM grid_raw").fetchone()[0]

    did = rehearsal.seed(market.conn)

    assert market.conn.execute("SELECT count(*) FROM grid_raw").fetchone()[0] == before
    n, run_ids, actions = market.conn.execute(
        "SELECT count(*), array_agg(DISTINCT run_id), array_agg(DISTINCT action) FROM decisions"
    ).fetchone()
    assert n == 48 and run_ids == ["selftest"] and set(actions) == {"charge", "discharge", "hold"}
    assert (
        market.conn.execute("SELECT action FROM decisions WHERE decision_id = %s", (did,)).fetchone()[0]
        == "charge"
    )

    rows = run_audit(market.conn, did, mode="inprocess")  # replayable: every period has a price
    assert all(r.error is None for r in rows)

    removed = rehearsal.remove(market.conn)
    assert removed == 48
    for table in ("decisions", "audits", "battery_state"):
        assert market.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_seed_without_prices_fails_clearly(market):
    import pytest

    with pytest.raises(RuntimeError, match="no day with 48 consecutive prices"):
        rehearsal.seed(market.conn)
