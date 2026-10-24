"""Shifting moves the schedule in the written SoC path; rows that wrap around become hold."""

import numpy as np
import pytest

from tempo.audit.shifts import ReplayError, replay_shift

from .conftest import T0, direct_pnl, targets


def soc_increases(rows, start):
    soc = np.array([start] + [r[1] for r in rows])
    return [k for k, d in enumerate(np.diff(soc)) if d > 1e-12]


def test_plus_one_moves_charge_later(market):
    mw = np.zeros(48)
    mw[4:8] = 1.0
    market.prices(targets(), np.full(48, 50.0))
    did = market.decisions(mw)
    market.start_soc(0.0)

    replay_shift(market.conn, did, 0, "s0")
    replay_shift(market.conn, did, 1, "s1")

    assert soc_increases(market.state("s0"), 0.0) == [4, 5, 6, 7]
    assert soc_increases(market.state("s1"), 0.0) == [5, 6, 7, 8]


def test_minus_two_drops_wrapped_rows(market):
    mw = np.zeros(48)
    mw[0:2] = 1.0  # charge in the first two periods
    mw[10] = -1.0
    prices = np.full(48, 40.0)
    prices[10] = 120.0
    prices[8] = 90.0
    market.prices(targets(), prices)
    did = market.decisions(mw)

    pnl = replay_shift(market.conn, did, -2, "m2")

    expected_mw = np.zeros(48)
    expected_mw[8] = -1.0  # discharge moves 2 earlier; both charges roll off the front and are dropped
    assert pnl == pytest.approx(direct_pnl(expected_mw, prices, soc=1.0), abs=0.005)
    assert soc_increases(market.state("m2"), 1.0) == []  # no charging anywhere, nothing wrapped to the end


def test_missing_prices_raise(market):
    market.prices(targets()[:40], np.full(40, 50.0))
    did = market.decisions(np.zeros(48))
    with pytest.raises(ReplayError, match="8 of 48 periods have no actual price"):
        replay_shift(market.conn, did, 0, "x")


def test_unknown_decision_raises(market):
    with pytest.raises(ReplayError, match="not found"):
        replay_shift(market.conn, 999_999, 0, "x")


def test_uses_whole_batch_from_any_decision_id(market):
    mw = np.zeros(48)
    mw[3] = 1.0
    market.prices(targets(), np.full(48, 50.0))
    first = market.decisions(mw)
    assert replay_shift(market.conn, first + 20, 0, "a") == replay_shift(market.conn, first, 0, "b")


def test_other_batches_are_ignored(market):
    market.prices(targets(), np.full(48, 50.0))
    market.prices(targets(T0 + (targets()[0] - T0) * 2), np.full(48, 50.0))
    did = market.decisions(np.zeros(48))
    market.decisions(np.ones(48), decided_at=T0 + (targets()[0] - T0) * 2)  # a later batch
    market.decisions(np.ones(48), run_id="backtest-1")  # same time, other run
    assert replay_shift(market.conn, did, 0, "x") == 0.0
