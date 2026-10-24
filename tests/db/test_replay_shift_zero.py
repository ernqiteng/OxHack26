"""replay_shift with shift 0 equals simulate called directly on the same schedule and prices."""

import numpy as np
import pytest

from tempo.audit.refsim import resolve_sim
from tempo.audit.shifts import replay_shift

from .conftest import day_prices, direct_pnl, targets


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_shift_zero_equals_direct_simulate(market, seed):
    rng = np.random.default_rng(100 + seed)
    mw = rng.choice([-1.0, 0.0, 0.0, 1.0], size=48)
    prices = day_prices(seed)
    market.prices(targets(), prices)
    did = market.decisions(mw)

    pnl = replay_shift(market.conn, did, 0, "test")

    assert pnl == pytest.approx(direct_pnl(mw, prices, soc=1.0), abs=0.005)  # to the penny
    rows = market.state("test")
    assert len(rows) == 48
    assert rows[-1][2] == pytest.approx(pnl, abs=1e-9)  # last cumulative PnL is the total


def test_start_soc_comes_from_original_run(market):
    mw = np.zeros(48)
    mw[:4] = 1.0
    prices = day_prices()
    market.prices(targets(), prices)
    did = market.decisions(mw)
    market.start_soc(0.25)

    pnl = replay_shift(market.conn, did, 0, "test")

    assert pnl == pytest.approx(direct_pnl(mw, prices, soc=0.25), abs=0.005)
    sim, _ = resolve_sim()
    first_soc = market.state("test")[0][1]
    assert first_soc == pytest.approx(0.25 + 0.5 * np.sqrt(0.9))


def test_replay_is_deterministic(market):
    mw = np.tile([1.0, 0.0, -1.0, 0.0], 12)
    market.prices(targets(), day_prices())
    did = market.decisions(mw)
    first = replay_shift(market.conn, did, 1, "test")
    second = replay_shift(market.conn, did, 1, "test")
    assert first == second
    assert len(market.state("test")) == 48  # rerun replaces rows, never duplicates
