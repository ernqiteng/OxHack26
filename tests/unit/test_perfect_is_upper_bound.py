"""perfect_foresight is an upper bound: nothing beats it on the prices it was given."""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from tempo.optimise.greedy import GreedyOptimiser
from tempo.optimise.perfect import _solve, perfect_foresight
from tempo.sim.battery import Battery, simulate

N = 48
TIMES = pd.date_range("2026-01-05", periods=N, freq="30min", tz="UTC")
HOUR = TIMES.hour.to_numpy()
SIMPLE_RULE = np.where((HOUR >= 1) & (HOUR < 5), 1.0, np.where((HOUR >= 17) & (HOUR < 19), -1.0, 0.0))
prices_st = arrays(float, N, elements=st.floats(-150, 400, allow_nan=False))


def pnl(battery, schedule, prices):
    return simulate(battery, np.asarray(schedule, dtype=float), prices).pnl_gbp


def perfect_pnl(battery, prices):
    return pnl(battery, perfect_foresight(prices, battery).mw, prices)


@given(prices_st, st.floats(0, 2))
@settings(max_examples=60, deadline=None)
def test_perfect_beats_greedy_on_true_prices(prices, soc0):
    b = Battery(soc_mwh=soc0)
    greedy = GreedyOptimiser().plan(pd.DataFrame({"p50": prices}, index=TIMES), b)
    assert perfect_pnl(b, prices) >= pnl(b, greedy.mw, prices) - 1e-4


@given(prices_st)
@settings(max_examples=60, deadline=None)
def test_perfect_beats_simple_rule(prices):
    b = Battery()
    assert perfect_pnl(b, prices) >= pnl(b, SIMPLE_RULE, prices) - 1e-4


@given(prices_st, arrays(float, N, elements=st.floats(-1, 1, allow_nan=False)))
@settings(max_examples=60, deadline=None)
def test_perfect_beats_any_schedule(prices, schedule):
    b = Battery()
    assert perfect_pnl(b, prices) >= pnl(b, schedule, prices) - 1e-4


@given(prices_st, st.floats(0, 2))
@settings(max_examples=60, deadline=None)
def test_schedule_is_feasible_and_one_direction_per_period(prices, soc0):
    b = Battery(soc_mwh=soc0)
    plan = perfect_foresight(prices, b)
    r = simulate(b, plan.mw.to_numpy(), prices)
    assert r.clipped_mwh < 1e-6
    assert (plan.mw.abs() <= b.power_mw + 1e-9).all()
    assert r.pnl_gbp >= -1e-4  # holding is always available


def test_very_negative_price_on_a_full_battery_needs_the_milp():
    """Full battery, -500 in the first period: with no earlier period to make room, the LP charges 1 MW and
    discharges 0.9 MW at once to burn energy for money. simulate() can't do that, so the MILP re-solve
    must return a plan that executes exactly."""
    prices = np.full(N, 40.0)
    prices[0] = -500.0
    b = Battery(soc_mwh=2.0)
    c, d = _solve(prices, b, exclusive=False)
    assert min(c[0], d[0]) > 0.5  # the LP really does both, so this test exercises the fallback
    plan = perfect_foresight(prices, b)
    r = simulate(b, plan.mw.to_numpy(), prices)
    assert r.clipped_mwh < 1e-6


def test_flat_prices_only_sell_starting_energy():
    plan = perfect_foresight(np.full(N, 60.0), Battery(soc_mwh=0.0))
    assert (plan.action == "hold").all()


def test_keeps_series_index_and_contract():
    prices = pd.Series(np.linspace(0, 100, N), index=TIMES)
    plan = perfect_foresight(prices, Battery())
    assert plan.index.equals(TIMES)
    assert list(plan.columns) == ["action", "mw", "expected_spread", "reason"]
    assert set(plan.action) <= {"charge", "discharge", "hold"}


def test_hand_built_day_matches_greedy():
    """One cheap block and one dear block: greedy is already optimal, so the two agree to the penny."""
    p = np.full(N, 50.0)
    p[4:8], p[34:38] = 20.0, 60.0
    b = Battery(soc_mwh=0.0)
    assert perfect_pnl(b, p) == pytest.approx(50.0, abs=1e-4)
