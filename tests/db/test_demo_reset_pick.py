"""Decision picking on the local DB: only fully priced live batches, scored by a real in-process audit,
best first (as decided wins, hold nearby, biggest cost of acting later)."""

from datetime import timedelta

import numpy as np

from tempo.audit.preflight import find_candidates

from .conftest import T0, targets


def test_picks_the_decision_whose_timing_was_best(market):
    prices = np.full(48, 50.0)
    prices[4:8] = 10.0  # cheap window exactly where the good batch charges
    prices[30:34] = 120.0
    market.prices(targets(), prices)

    good = np.zeros(48)
    good[4:8], good[30:34] = 1.0, -1.0
    good[40] = 0.0  # holds exist in this batch
    good_id = market.decisions(good)

    late = T0 + timedelta(hours=1)  # a later batch, charging 2 periods off the cheap window
    market.prices(targets(late), np.r_[prices[2:], [50.0, 50.0]])
    bad = np.zeros(48)
    bad[0:4], bad[28:32] = 1.0, -1.0
    market.decisions(bad, decided_at=late)

    market.decisions(np.ones(48), decided_at=T0 + timedelta(days=5))  # no prices: never a candidate

    cands = find_candidates(market.conn)

    assert cands[0].decided_at == T0  # the well-timed batch ranks first
    assert cands[0].decision_id == good_id + 4  # its first non-hold row: the charge at period 4
    assert cands[0].zero_is_best and cands[0].has_hold and cands[0].action == "charge"
    assert cands[0].later_delta < 0
    assert "Charging one period later would have cost" in cands[0].sentence()
    assert len(cands) == 2
