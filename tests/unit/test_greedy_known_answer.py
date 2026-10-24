"""GreedyOptimiser on a hand-built day: cheap at periods 4 to 7, expensive at 34 to 37."""

import numpy as np
import pandas as pd
import pytest

from tempo.optimise.greedy import GreedyOptimiser
from tempo.sim.battery import Battery, simulate

TIMES = pd.date_range("2026-01-05", periods=48, freq="30min", tz="UTC")
EMPTY = Battery(soc_mwh=0.0)


def quantiles(p50):
    p50 = np.asarray(p50, dtype=float)
    return pd.DataFrame({"p10": p50 - 5, "p50": p50, "p90": p50 + 5}, index=TIMES)


def hand_built_day():
    """Base 50 so that only cheap -> dear pays: 0.9*60 - 20 - 9 = 25 > 0, 0.9*60 - 50 - 9 < 0."""
    p = np.full(48, 50.0)
    p[4:8] = 20.0
    p[34:38] = 60.0
    return p


def test_charges_cheap_discharges_dear():
    plan = GreedyOptimiser().plan(quantiles(hand_built_day()), EMPTY)
    assert list(plan.index[plan.action == "charge"]) == list(TIMES[4:8])
    assert list(plan.index[plan.action == "discharge"]) == list(TIMES[34:38])
    assert (plan.mw[plan.action == "charge"] == 1.0).all()
    # 4 x 0.5 MWh bought stores 1.897 MWh; three full-power sells draw 0.527 each, the last takes the rest
    assert plan.mw[plan.action == "discharge"].to_numpy() == pytest.approx([-1.0, -1.0, -1.0, -0.6])


def test_pnl_by_hand():
    """Buy 4 x 0.5 = 2 MWh at 20 = 40. 90% comes back: sell 1.8 MWh at 60 = 108. Gross 68.
    1.8 MWh sold / 2 MWh capacity = 0.9 cycles x GBP 20 = 18. Net 50."""
    p = hand_built_day()
    plan = GreedyOptimiser().plan(quantiles(p), EMPTY)
    r = simulate(EMPTY, plan.mw.to_numpy(), p)
    assert r.gross_pnl_gbp == pytest.approx(68.0)
    assert r.cycle_cost_gbp == pytest.approx(18.0)
    assert r.pnl_gbp == pytest.approx(50.0)
    assert r.clipped_mwh == pytest.approx(0.0, abs=1e-9)
    assert r.soc_path[-1] == pytest.approx(0.0, abs=1e-9)


def test_output_contract():
    plan = GreedyOptimiser().plan(quantiles(hand_built_day()), EMPTY)
    assert list(plan.columns) == ["action", "mw", "expected_spread", "reason"]
    assert plan.index.equals(TIMES)
    assert set(plan.action) <= {"charge", "discharge", "hold"}
    assert (plan.reason.str.len() > 0).all()
    traded = plan[plan.action != "hold"]
    assert (traded.expected_spread == 40.0).all()  # 60 - 20


def test_sells_starting_energy_at_the_best_price():
    """A battery that starts with 1 MWh and sees no cheap period sells it at the dearest periods."""
    p = np.full(48, 30.0)
    p[36:38] = 90.0
    plan = GreedyOptimiser().plan(quantiles(p), Battery())
    assert list(plan.index[plan.action == "discharge"]) == list(TIMES[36:38])
    assert plan.reason.iloc[36].startswith("sell stored energy")
