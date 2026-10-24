"""Battery dataclass and simulate(battery, schedule_mw, prices) -> SimResult.

Owner: Ernqi. See docs/ernqi.md.

Contract frozen at Gate 0 (docs/plan.md 2.2). Defaults are the B8 item 4 decisions in docs/needs.md
and match BATTERY_* in .env.example. Rules are docs/ernqi.md Phase 1 task 1; the known answers in
tests/fixtures/synthetic.py check them.

Energy accounting, per half-hour period with grid energy e = |mw| * 0.5 MWh:
    charge:    buy e from the grid, SoC rises by e * sqrt(eff)
    discharge: SoC falls by e / sqrt(eff), sell e to the grid
so a full round trip returns eff of what was bought. If a period would push SoC outside
[0, capacity], only the part that fits is traded; the rest is clipped_mwh (grid side), never
bought or sold. Cycles = MWh sold to the grid / capacity.
"""

from dataclasses import dataclass
from math import sqrt

import numpy as np


@dataclass
class Battery:
    capacity_mwh: float = 2.0
    power_mw: float = 1.0
    rt_efficiency: float = 0.90  # round trip, split sqrt(eff) on charge and on discharge
    cycle_cost_gbp: float = 20.0  # per full cycle (capacity_mwh delivered)
    soc_mwh: float = 1.0  # starting state of charge


@dataclass
class SimResult:
    pnl_gbp: float  # gross_pnl_gbp - cycle_cost_gbp
    gross_pnl_gbp: float
    cycle_cost_gbp: float
    soc_path: np.ndarray  # SoC after each period, MWh
    cycles: float
    clipped_mwh: float  # energy the schedule asked for that did not fit, never bought or sold


def simulate(battery: Battery, schedule_mw: np.ndarray, prices: np.ndarray) -> SimResult:
    """schedule_mw[k] > 0 charges (buys), < 0 discharges (sells), for half-hour period k at prices[k]."""
    schedule_mw = np.asarray(schedule_mw, dtype=float)
    prices = np.asarray(prices, dtype=float)
    if schedule_mw.shape != prices.shape or schedule_mw.ndim != 1:
        raise ValueError(
            f"schedule_mw {schedule_mw.shape} and prices {prices.shape} must be equal-length 1-D"
        )

    s = sqrt(battery.rt_efficiency)
    cap = battery.capacity_mwh
    soc = battery.soc_mwh
    gross = sold = clipped = 0.0
    soc_path = np.empty(len(prices))

    for k, (mw, price) in enumerate(zip(np.clip(schedule_mw, -battery.power_mw, battery.power_mw), prices)):
        requested = abs(mw) * 0.5
        if mw > 0:
            stored = min(requested * s, cap - soc)
            traded = stored / s
            soc = min(soc + stored, cap)
            gross -= traded * price
        elif mw < 0:
            drawn = min(requested / s, soc)
            traded = drawn * s
            soc = max(soc - drawn, 0.0)
            gross += traded * price
            sold += traded
        else:
            traded = 0.0
        clipped += requested - traded
        soc_path[k] = soc

    cycles = sold / cap
    cycle_cost = cycles * battery.cycle_cost_gbp
    return SimResult(
        pnl_gbp=gross - cycle_cost,
        gross_pnl_gbp=gross,
        cycle_cost_gbp=cycle_cost,
        soc_path=soc_path,
        cycles=cycles,
        clipped_mwh=clipped,
    )
