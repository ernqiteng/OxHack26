"""Battery and simulate contract (docs/plan.md 2.2). Ayo's replay and worker code depends on these."""

import inspect
from dataclasses import fields

import numpy as np

from tempo.sim.battery import Battery, SimResult, simulate


def test_battery_defaults():
    b = Battery()
    assert (b.capacity_mwh, b.power_mw, b.rt_efficiency, b.cycle_cost_gbp, b.soc_mwh) == (2.0, 1.0, 0.90, 20.0, 1.0)


def test_simulate_signature():
    params = inspect.signature(simulate).parameters
    assert list(params) == ["battery", "schedule_mw", "prices"]
    assert params["schedule_mw"].annotation is np.ndarray
    assert params["prices"].annotation is np.ndarray
    assert inspect.signature(simulate).return_annotation is SimResult


def test_sim_result_fields():
    assert [f.name for f in fields(SimResult)] == [
        "pnl_gbp",
        "gross_pnl_gbp",
        "cycle_cost_gbp",
        "soc_path",
        "cycles",
        "clipped_mwh",
    ]
