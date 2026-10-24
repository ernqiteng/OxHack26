"""LPOptimiser holds on flat p50, with a reason on every row."""

import numpy as np
import pandas as pd

from tempo.optimise.lp import LPOptimiser
from tempo.sim.battery import Battery

TIMES = pd.date_range("2026-01-05", periods=48, freq="30min", tz="UTC")
FLAT = pd.DataFrame({"p10": 55.0, "p50": 60.0, "p90": 65.0}, index=TIMES)


def test_flat_p50_all_hold():
    """Empty battery: nothing pays. (With stored energy the LP sells it above wear, as greedy does.)"""
    plan = LPOptimiser().plan(FLAT, Battery(soc_mwh=0.0))
    assert (plan.action == "hold").all()
    assert (plan.mw == 0).all()
    assert plan.reason.str.startswith("hold: spread 0.00 <= cost").all()


def test_flat_p50_with_stored_energy_sells_it_and_says_why():
    plan = LPOptimiser().plan(FLAT, Battery())
    sold = plan[plan.action == "discharge"]
    assert len(sold) > 0 and (plan.action != "charge").all()
    assert sold.reason.str.contains("selling stored energy at 60.00 > wear 10.00/MWh").all()
    assert np.isclose(-sold.mw.sum() * 0.5, Battery().soc_mwh * np.sqrt(0.9))  # all of it, after losses
