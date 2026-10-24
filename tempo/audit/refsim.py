"""Reference battery simulator, written to the spec in docs/ernqi.md Phase 1 task 1.

Owner: Ayo. A stand-in so the timing audit can be built and tested before Ernqi's `tempo.sim.battery`
lands. `resolve_sim()` prefers Ernqi's module the moment its `simulate` stops raising NotImplementedError,
so this file is never used once the real one exists. Do not tune physics here; change Ernqi's instead.

Spec (ernqi.md):
- schedule_mw[k] > 0 charges (buys), < 0 discharges (sells); clipped to +-power_mw.
- Energy per period = mw * 0.5 MWh at the grid. Charging adds energy * sqrt(eff) to SoC; discharging
  removes energy / sqrt(eff) from SoC.
- SoC stays in [0, capacity]; energy that would breach a bound is not traded and is reported as clipped_mwh.
- Period cash = -mw * 0.5 * price. Cycles = discharged MWh / capacity; cycle cost subtracted from PnL.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

PERIOD_HOURS = 0.5


@dataclass
class Battery:
    capacity_mwh: float = 2.0
    power_mw: float = 1.0
    rt_efficiency: float = 0.90
    cycle_cost_gbp: float = 20.0
    soc_mwh: float = 1.0


@dataclass
class SimResult:
    pnl_gbp: float
    gross_pnl_gbp: float
    cycle_cost_gbp: float
    soc_path: np.ndarray
    cycles: float
    clipped_mwh: float
    executed_mw: np.ndarray = field(default_factory=lambda: np.zeros(0))


def simulate(battery: Battery, schedule_mw: np.ndarray, prices: np.ndarray) -> SimResult:
    schedule = np.asarray(schedule_mw, dtype=float)
    prices = np.asarray(prices, dtype=float)
    if schedule.shape != prices.shape:
        raise ValueError(f"schedule {schedule.shape} and prices {prices.shape} differ in shape")
    leg = math.sqrt(battery.rt_efficiency)
    soc = float(battery.soc_mwh)
    soc_path = np.empty(len(schedule))
    executed = np.zeros(len(schedule))
    gross = clipped = discharged = 0.0
    for k, (mw, price) in enumerate(zip(schedule, prices, strict=True)):
        mw = float(np.clip(mw, -battery.power_mw, battery.power_mw))
        want = mw * PERIOD_HOURS  # grid-side MWh, signed
        if want > 0:
            grid = min(want, (battery.capacity_mwh - soc) / leg)
            soc += grid * leg
        elif want < 0:
            grid = -min(-want, soc * leg)
            soc += grid / leg
            discharged += -grid
        else:
            grid = 0.0
        soc = min(max(soc, 0.0), battery.capacity_mwh)  # float dust only
        clipped += abs(want - grid)
        executed[k] = grid / PERIOD_HOURS
        gross += -grid * price
        soc_path[k] = soc
    cycles = discharged / battery.capacity_mwh
    cycle_cost = cycles * battery.cycle_cost_gbp
    return SimResult(
        pnl_gbp=gross - cycle_cost,
        gross_pnl_gbp=gross,
        cycle_cost_gbp=cycle_cost,
        soc_path=soc_path,
        cycles=cycles,
        clipped_mwh=clipped,
        executed_mw=executed,
    )


def resolve_sim() -> tuple[SimpleNamespace, str]:
    """Return (namespace with Battery and simulate, name). Ernqi's module if implemented, else this one."""
    try:
        from tempo.sim import battery as ernqi

        probe = ernqi.simulate(ernqi.Battery(), np.zeros(1), np.zeros(1))
        _ = probe.pnl_gbp, probe.soc_path
        return SimpleNamespace(Battery=ernqi.Battery, simulate=ernqi.simulate), "tempo.sim.battery"
    except (ImportError, AttributeError, NotImplementedError, TypeError):
        return SimpleNamespace(Battery=Battery, simulate=simulate), "reference (tempo.audit.refsim)"
