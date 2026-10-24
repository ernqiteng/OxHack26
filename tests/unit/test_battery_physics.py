"""simulate() physics: limits, round-trip loss, conservation, clipping. docs/ernqi.md Phase 1."""

from math import sqrt

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from tempo.sim.battery import Battery, simulate

N = 48
mw = st.floats(-3, 3, allow_nan=False)  # beyond ±power_mw on purpose, simulate must clip
price = st.floats(-100, 500, allow_nan=False)


@st.composite
def schedule_and_prices(draw, n=N):
    return draw(arrays(float, n, elements=mw)), draw(arrays(float, n, elements=price))


@given(schedule_and_prices())
@settings(max_examples=200)
def test_soc_always_within_capacity(sp):
    b = Battery()
    r = simulate(b, *sp)
    assert (r.soc_path >= 0).all() and (r.soc_path <= b.capacity_mwh).all()


@given(schedule_and_prices())
@settings(max_examples=200)
def test_power_clipped_to_limit(sp):
    """SoC never moves faster than power_mw allows in one half-hour, whatever the schedule asks."""
    b = Battery()
    r = simulate(b, *sp)
    steps = np.diff(np.concatenate([[b.soc_mwh], r.soc_path]))
    s = sqrt(b.rt_efficiency)
    assert (steps <= b.power_mw * 0.5 * s + 1e-12).all()
    assert (steps >= -b.power_mw * 0.5 / s - 1e-12).all()


@given(schedule_and_prices())
@settings(max_examples=200)
def test_energy_conservation(sp):
    """Grid-side accounting with sqrt(eff) each way: bought*s - sold/s == soc_end - soc_start.

    ernqi.md writes this as sum(charged) * eff == sum(discharged) + delta_soc, which only holds when
    delta_soc == 0; this is the general form. Bought and sold are recovered from the PnL at unit prices.
    """
    schedule, _ = sp
    b = Battery()
    s = sqrt(b.rt_efficiency)
    # price 1 when charging, 0 otherwise -> gross = -bought; and the reverse for sold
    bought = -simulate(b, schedule, (schedule > 0).astype(float)).gross_pnl_gbp
    sold = simulate(b, schedule, (schedule < 0).astype(float)).gross_pnl_gbp
    soc_end = simulate(b, schedule, np.zeros(N)).soc_path[-1]
    assert bought * s - sold / s == pytest.approx(soc_end - b.soc_mwh, abs=1e-9)


def test_full_round_trip_at_same_price_loses_efficiency():
    b = Battery(soc_mwh=0.0)
    p = 50.0
    schedule = np.array([1.0] * 4 + [-1.0] * 4)  # 2 MWh bought (fits: 1.897 MWh stored), then drain
    r = simulate(b, schedule, np.full(8, p))
    bought = 4 * 0.5
    assert r.soc_path[-1] == pytest.approx(0.0, abs=1e-12)
    assert r.gross_pnl_gbp < 0
    assert r.gross_pnl_gbp == pytest.approx(-(1 - b.rt_efficiency) * bought * p, abs=1e-9)


def test_zero_schedule_zero_pnl_and_cycles():
    r = simulate(Battery(), np.zeros(N), np.linspace(-50, 200, N))
    assert r.pnl_gbp == 0 and r.gross_pnl_gbp == 0 and r.cycles == 0 and r.clipped_mwh == 0
    assert (r.soc_path == Battery().soc_mwh).all()


def test_overfill_is_clipped_not_bought():
    """Start full and keep charging: nothing is bought, everything requested is clipped."""
    b = Battery(soc_mwh=2.0)
    r = simulate(b, np.ones(4), np.full(4, 30.0))
    assert r.gross_pnl_gbp == 0 and r.clipped_mwh == pytest.approx(2.0)


def test_one_discharge_by_hand():
    """1 MWh stored, sell 1 MW for one period at GBP 100: 0.5 MWh sold, 0.5/sqrt(0.9) MWh drawn."""
    b = Battery()
    r = simulate(b, np.array([-1.0]), np.array([100.0]))
    assert r.gross_pnl_gbp == pytest.approx(50.0)
    assert r.cycles == pytest.approx(0.25)
    assert r.cycle_cost_gbp == pytest.approx(5.0)
    assert r.pnl_gbp == pytest.approx(45.0)
    assert r.soc_path[0] == pytest.approx(1.0 - 0.5 / sqrt(0.9))


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError):
        simulate(Battery(), np.zeros(3), np.zeros(4))
