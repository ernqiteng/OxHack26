"""Battery dataclass and simulate(battery, schedule_mw, prices) -> SimResult.

Owner: Ernqi. See docs/ernqi.md.

Contract frozen at Gate 0 (docs/plan.md 2.2). Defaults are the B8 item 4 decisions in docs/needs.md
and match BATTERY_* in .env.example. simulate() is a stub until Phase 1; the rules it will follow are
in docs/ernqi.md Phase 1 task 1 and the known answers in tests/fixtures/synthetic.py.
"""

from dataclasses import dataclass

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
    raise NotImplementedError("Phase 1, see docs/ernqi.md")
