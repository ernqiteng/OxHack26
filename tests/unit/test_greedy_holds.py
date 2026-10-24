"""GreedyOptimiser holds with a reason when nothing pays or the battery is at a limit."""

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from tempo.optimise.greedy import GreedyOptimiser
from tempo.sim.battery import Battery, simulate

TIMES = pd.date_range("2026-01-05", periods=48, freq="30min", tz="UTC")
EMPTY = Battery(soc_mwh=0.0)  # with stored energy, greedy sells it whenever price > wear, see greedy.py


def quantiles(p50):
    p50 = np.asarray(p50, dtype=float)
    return pd.DataFrame({"p10": p50 - 5, "p50": p50, "p90": p50 + 5}, index=TIMES)


def test_flat_prices_hold_everywhere_with_reason():
    plan = GreedyOptimiser().plan(quantiles(np.full(48, 60.0)), EMPTY)
    assert (plan.action == "hold").all()
    assert (plan.mw == 0).all()
    assert plan.reason.str.startswith("hold: spread 0.00 <= cost").all()


def test_small_spread_holds_on_cost():
    p = np.full(48, 60.0)
    p[40] = 70.0  # 10 above, but losses + wear are 16
    plan = GreedyOptimiser().plan(quantiles(p), EMPTY)
    assert (plan.action == "hold").all()
    assert "<= cost" in plan.reason.iloc[40]


def test_full_battery_holds_with_limit_reason():
    """Full until period 34, so the profitable 4 -> 34 pair has no room: hold at 4, say why."""
    p = np.full(48, 5.0)  # below wear, so stored energy is not sold early
    p[4] = -20.0
    p[34] = 30.0
    plan = GreedyOptimiser().plan(quantiles(p), Battery(soc_mwh=2.0))
    assert plan.action.iloc[4] == "hold"
    assert "battery full" in plan.reason.iloc[4]
    assert plan.action.iloc[34] == "discharge"  # sells some stored energy instead


@given(
    arrays(float, 48, elements=st.floats(-50, 300, allow_nan=False)),
    st.floats(0, 2),
)
@settings(max_examples=100, deadline=None)
def test_plan_is_feasible_and_profitable_on_its_own_forecast(p, soc0):
    """If the forecast is right, every greedy plan fits the battery and makes money (or holds)."""
    b = Battery(soc_mwh=soc0)
    plan = GreedyOptimiser().plan(quantiles(p), b)
    r = simulate(b, plan.mw.to_numpy(), p)
    assert r.clipped_mwh < 1e-6
    assert r.pnl_gbp >= -1e-6
    assert (plan.reason.str.len() > 0).all()
    assert ((plan.action == "hold") == (plan.mw == 0)).all()
