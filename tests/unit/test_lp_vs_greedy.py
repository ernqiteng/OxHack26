"""LPOptimiser: at least as good as greedy on its own forecast, and always executable."""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from tempo.optimise.greedy import GreedyOptimiser
from tempo.optimise.lp import LPOptimiser
from tempo.sim.battery import Battery, simulate

N = 48
TIMES = pd.date_range("2026-01-05", periods=N, freq="30min", tz="UTC")


@st.composite
def quantile_frames(draw):
    p50 = draw(arrays(float, N, elements=st.floats(-100, 400, allow_nan=False)))
    lo = draw(arrays(float, N, elements=st.floats(0, 60, allow_nan=False)))
    hi = draw(arrays(float, N, elements=st.floats(0, 60, allow_nan=False)))
    return pd.DataFrame({"p10": p50 - lo, "p50": p50, "p90": p50 + hi}, index=TIMES)


def pnl(b, plan, prices):
    return simulate(b, plan.mw.to_numpy(), prices)


@given(quantile_frames(), st.floats(0, 2))
@settings(max_examples=60, deadline=None)
def test_lp_at_least_greedy_on_p50(q, soc0):
    b = Battery(soc_mwh=soc0)
    p50 = q.p50.to_numpy()
    lp = pnl(b, LPOptimiser().plan(q, b), p50).pnl_gbp
    greedy = pnl(b, GreedyOptimiser().plan(q, b), p50).pnl_gbp
    assert lp >= greedy - 1e-3  # TINY_MW rounding can cost a fraction of a penny


@given(quantile_frames(), st.floats(0, 2), st.booleans())
@settings(max_examples=60, deadline=None)
def test_lp_schedule_respects_every_constraint(q, soc0, conservative):
    b = Battery(soc_mwh=soc0)
    plan = LPOptimiser(conservative=conservative).plan(q, b)
    r = pnl(b, plan, q.p50.to_numpy())
    assert r.clipped_mwh < 1e-6  # nothing the battery could not do
    assert (plan.mw.abs() <= b.power_mw + 1e-9).all()
    assert set(plan.action) <= {"charge", "discharge", "hold"}
    assert ((plan.action == "hold") == (plan.mw == 0)).all()
    assert (plan.reason.str.len() > 0).all()


def test_conservative_trades_less_when_bands_are_wide():
    """p50 spread pays, but buying at p90 and selling at p10 does not: the conservative LP holds."""
    p50 = np.full(N, 50.0)
    p50[4:8], p50[34:38] = 20.0, 60.0
    q = pd.DataFrame({"p10": p50 - 20, "p50": p50, "p90": p50 + 20}, index=TIMES)
    b = Battery(soc_mwh=0.0)
    assert (LPOptimiser().plan(q, b).action != "hold").any()
    assert (LPOptimiser(conservative=True).plan(q, b).action == "hold").all()


def test_cycle_reasons_name_the_gate():
    p50 = np.full(N, 50.0)
    p50[4:8], p50[34:38] = 20.0, 60.0
    q = pd.DataFrame({"p10": p50, "p50": p50, "p90": p50}, index=TIMES)
    plan = LPOptimiser().plan(q, Battery(soc_mwh=0.0))
    traded = plan[plan.action != "hold"]
    assert traded.reason.str.contains("LP cycle: spread 40.00 > cost").all()
    assert traded.expected_spread.to_numpy() == pytest.approx([40.0] * len(traded))
    assert simulate(Battery(soc_mwh=0.0), plan.mw.to_numpy(), p50).pnl_gbp == pytest.approx(50.0, abs=1e-3)
