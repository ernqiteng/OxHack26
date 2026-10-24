"""cost_gate: holds on flat prices, exact threshold, readable reasons, agrees with simulate()."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tempo.optimise.gate import cost_gate
from tempo.sim.battery import Battery, simulate

B = Battery()
# default battery, sell at 100: efficiency loss 10.00 + degradation 9.00 -> cost 19.00
SELL = 100.0
THRESHOLD_BUY = SELL - 19.0


def test_flat_prices_not_ok():
    for p in (-20.0, 0.0, 50.0, 300.0):
        ok, spread, _ = cost_gate(p, p, B)
        assert not ok and spread == 0


def test_spread_exactly_at_threshold_not_ok():
    ok, spread, _ = cost_gate(THRESHOLD_BUY, SELL, B)
    assert not ok and spread == pytest.approx(19.0)


def test_one_penny_above_threshold_ok():
    ok, spread, _ = cost_gate(THRESHOLD_BUY - 0.01, SELL, B)
    assert ok and spread == pytest.approx(19.01)


def test_reason_contains_the_numbers():
    _, _, hold = cost_gate(90.0, SELL, B)
    assert hold == "spread 10.00 <= cost 19.00 (efficiency loss 10.00 at 10% + degradation 9.00/MWh)"
    _, _, go = cost_gate(40.0, SELL, B)
    assert go.startswith("spread 60.00 > cost 19.00")


def test_negative_buy_price_can_pass():
    ok, _, _ = cost_gate(-10.0, 15.0, B)  # paid to charge on a windy night
    assert ok


@given(st.floats(-100, 400), st.floats(-100, 400))
def test_gate_agrees_with_simulate(buy, sell):
    """ok exactly when one full charge then full discharge at these prices makes money in simulate()."""
    b = Battery(soc_mwh=0.0)
    schedule = np.array([1.0] * 4 + [-1.0] * 4)  # 2 MWh bought, all of it later sold back
    prices = np.array([buy] * 4 + [sell] * 4)
    pnl = simulate(b, schedule, prices).pnl_gbp
    ok, _, _ = cost_gate(buy, sell, b)
    if abs(pnl) > 1e-6:  # skip knife-edge cases where float rounding decides
        assert ok == (pnl > 0)
