"""LPOptimiser: at least as good as greedy on its own forecast, and always executable."""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from tempo.optimise.greedy import GreedyOptimiser
from tempo.optimise.lp import TINY_MW, LPOptimiser
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
    # The LP refuses trades under TINY_MW; one refused half-hour is worth at most TINY_MW * 0.5 h * price.
    assert lp >= greedy - 1e-3 - TINY_MW * 0.5 * np.abs(p50).max()


def test_lp_refuses_a_sub_kilowatt_sale_that_greedy_makes():
    """Hypothesis found this: a flat 339 GBP/MWh and 3.2e-6 MWh stored. Greedy sells the sliver (0.1p); the
    LP's sale is 6e-6 MW, under TINY_MW, so it holds. By design, and within the bound above."""
    p = np.full(N, 339.0)
    q = pd.DataFrame({"p10": p, "p50": p, "p90": p}, index=TIMES)
    b = Battery(soc_mwh=3.2068191544546527e-06)
    lp, greedy = LPOptimiser().plan(q, b), GreedyOptimiser().plan(q, b)
    assert (lp.action == "hold").all()
    gap = pnl(b, greedy, p).pnl_gbp - pnl(b, lp, p).pnl_gbp
    assert 0 < gap <= TINY_MW * 0.5 * 339.0


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


def test_zeroing_a_tiny_sale_does_not_overfill():
    """Hypothesis found this: the LP sells the 6e-5 MWh it starts with (0.1 kW, under TINY_MW) and then
    charges to exactly full. Zeroing that sale left the energy in, so the full charge overfilled."""
    p = np.full(N, 11.0)
    p[1:6] = 0.0
    q = pd.DataFrame({"p10": p, "p50": p, "p90": p}, index=TIMES)
    b = Battery(soc_mwh=6.103515625e-05)
    plan = LPOptimiser().plan(q, b)
    assert pnl(b, plan, p).clipped_mwh < 1e-9
    assert (plan.mw[plan.mw != 0].abs() >= 1e-3).all()


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
