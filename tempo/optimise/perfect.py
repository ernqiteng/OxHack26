"""perfect_foresight(prices, battery): the best any schedule could have done, knowing actual prices.

Owner: Ernqi. See docs/ernqi.md Phase 1 task 4.

Linear program on grid-side charge c[k] and discharge d[k] (MW), same physics as simulate():
    soc[k+1] = soc[k] + 0.5 * (c[k] * sqrt(eff) - d[k] / sqrt(eff)),  0 <= soc <= capacity
    maximise  sum(price * (d - c) * 0.5)  -  cycle_cost_gbp / capacity * sum(d) * 0.5
End SoC is free, as in the known answers. simulate() takes one net power per period, so if the LP
charges and discharges in the same period (only pays at very negative prices, to burn energy) it is
re-solved as a MILP that forbids it. Solver: HiGHS via cvxpy.
"""

from math import sqrt

import cvxpy as cp
import numpy as np
import pandas as pd

from tempo.sim.battery import Battery

EPS = 1e-7


def perfect_foresight(prices, battery: Battery) -> pd.DataFrame:
    """Returns one row per period: action, mw (+ charge, - discharge), expected_spread (NaN), reason."""
    index = prices.index if isinstance(prices, pd.Series) else pd.RangeIndex(len(prices))
    p = np.asarray(prices, dtype=float)

    c, d = _solve(p, battery, exclusive=False)
    if np.minimum(c, d).max() > EPS:
        c, d = _solve(p, battery, exclusive=True)

    mw = c - d
    mw[np.abs(mw) < EPS] = 0.0
    action = np.where(mw > 0, "charge", np.where(mw < 0, "discharge", "hold"))
    return pd.DataFrame(
        {"action": action, "mw": mw, "expected_spread": np.nan, "reason": "perfect foresight (actual prices)"},
        index=index,
    )


def _solve(p: np.ndarray, battery: Battery, exclusive: bool) -> tuple[np.ndarray, np.ndarray]:
    n, s, power = len(p), sqrt(battery.rt_efficiency), battery.power_mw
    c, d, soc = cp.Variable(n, nonneg=True), cp.Variable(n, nonneg=True), cp.Variable(n + 1)
    constraints = [
        soc[0] == battery.soc_mwh,
        soc[1:] == soc[:-1] + 0.5 * (c * s - d / s),
        soc >= 0,
        soc <= battery.capacity_mwh,
    ]
    if exclusive:
        charging = cp.Variable(n, boolean=True)
        constraints += [c <= power * charging, d <= power * (1 - charging)]
    else:
        constraints += [c <= power, d <= power]
    wear = battery.cycle_cost_gbp / battery.capacity_mwh
    objective = cp.Maximize(0.5 * (p @ (d - c)) - 0.5 * wear * cp.sum(d))
    problem = cp.Problem(objective, constraints)
    problem.solve(solver="HIGHS")
    if problem.status != cp.OPTIMAL:
        raise RuntimeError(f"perfect_foresight LP not solved: {problem.status}")
    return np.clip(c.value, 0, power), np.clip(d.value, 0, power)
