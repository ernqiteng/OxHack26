"""Reference simulator physics and shift_schedule; both are stand-ins checked against the ernqi.md spec."""

import numpy as np
import pytest

from tempo.audit.refsim import Battery, resolve_sim, simulate
from tempo.audit.shifts import shift_schedule


def test_shift_schedule_fills_wrapped_with_hold():
    mw = np.array([1.0, 2, 3, 4, 5])
    assert shift_schedule(mw, 0).tolist() == [1, 2, 3, 4, 5]
    assert shift_schedule(mw, 1).tolist() == [0, 1, 2, 3, 4]
    assert shift_schedule(mw, 2).tolist() == [0, 0, 1, 2, 3]
    assert shift_schedule(mw, -1).tolist() == [2, 3, 4, 5, 0]
    assert shift_schedule(mw, -2).tolist() == [3, 4, 5, 0, 0]


def test_zero_schedule_zero_pnl():
    r = simulate(Battery(), np.zeros(48), np.full(48, 50.0))
    assert r.pnl_gbp == 0 and r.cycles == 0 and r.clipped_mwh == 0


def test_round_trip_loses_efficiency():
    b = Battery(soc_mwh=0.0, cycle_cost_gbp=0.0)
    charge = 1.0  # MW for one period = 0.5 MWh in
    r = simulate(b, np.array([charge, -1.0, -1.0]), np.full(3, 100.0))
    # 0.5 MWh in at £100 -> SoC 0.5*sqrt(.9); out = SoC*sqrt(.9) = 0.45 MWh -> £45
    assert r.gross_pnl_gbp == pytest.approx(-50 + 45)
    assert r.soc_path[-1] == pytest.approx(0.0)
    assert r.clipped_mwh == pytest.approx(0.5 - 0.45 + 0.5)


def test_soc_stays_in_bounds_and_power_clipped():
    rng = np.random.default_rng(0)
    r = simulate(Battery(), rng.uniform(-3, 3, 500), rng.uniform(-50, 200, 500))
    assert r.soc_path.min() >= 0 and r.soc_path.max() <= 2.0
    assert np.abs(r.executed_mw).max() <= 1.0 + 1e-12


def test_cycle_cost_subtracted():
    r = simulate(Battery(soc_mwh=2.0), np.array([-1.0, -1.0]), np.full(2, 0.0))
    assert r.cycles == pytest.approx(0.5)
    assert r.pnl_gbp == pytest.approx(-10.0)


def test_resolve_sim_reports_which():
    sim, name = resolve_sim()
    assert callable(sim.simulate) and name


def test_refsim_matches_ernqi_fixture_known_answer():
    """Ernqi's fixture docstring: simple rule over the first 7 days nets £1264.8 (gross £1397.6,
    6.64 cycles, 15.0 MWh clipped), computed with an independent reference. The stand-in must agree."""
    import pandas as pd

    from tests.fixtures.synthetic import make_synthetic_market

    df = make_synthetic_market()
    mid = df[(df.dataset == "MID") & (df.series == "APXMIDP")].sort_values("start_time").iloc[: 7 * 48]
    local = pd.DatetimeIndex(mid.start_time).tz_convert("Europe/London")
    hour = local.hour + local.minute / 60
    mw = np.where((hour >= 1) & (hour < 5), 1.0, np.where((hour >= 17) & (hour < 19), -1.0, 0.0))

    r = simulate(Battery(), mw, mid.value.to_numpy())

    assert round(r.pnl_gbp, 1) == 1264.8
    assert round(r.gross_pnl_gbp, 1) == 1397.6
    assert round(r.cycles, 2) == 6.64
    assert round(r.clipped_mwh, 1) == 15.0
