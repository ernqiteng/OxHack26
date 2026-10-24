"""LPOptimiser.plan(): cvxpy linear program over 48 periods with SoC, power, efficiency, cycle cost.

Owner: Ernqi. See docs/ernqi.md Phase 2 task 4.

The same LP as perfect_foresight, solved on the forecast instead of actual prices: maximise
sum(p50 * (discharge - charge) * 0.5) - wear * sum(discharge) * 0.5, with simulate()'s physics, a free
end SoC, and the MILP re-solve if it would charge and discharge in one period. conservative=True prices
buys at p90 and sells at p10, so it only trades spreads that survive a bad forecast.

Reasons come after the solve: each cycle (a run of charge periods and the discharge periods that follow
before the next charge) is passed through cost_gate at its energy-weighted buy and sell prices. Holds get
GreedyOptimiser's explanation of the best pair they could have made. Flows under 1 kW are set to hold.
"""

import numpy as np
import pandas as pd

from tempo.optimise.gate import cost_gate
from tempo.optimise.greedy import GreedyOptimiser
from tempo.optimise.perfect import EPS, _solve
from tempo.sim.battery import Battery, simulate

TINY_MW = 1e-3


def _executable(mw: np.ndarray, battery: Battery) -> np.ndarray:
    """Zero flows under TINY_MW, then trim each period to what the battery can do. Zeroing is not free:
    dropping a tiny early sale leaves energy in the battery, so a later charge to exactly full overfills
    it. Trimming can make a flow tiny in turn, so repeat until nothing changes."""
    s = np.sqrt(battery.rt_efficiency)
    mw = mw.copy()
    for _ in range(len(mw) + 1):
        mw[np.abs(mw) < TINY_MW] = 0.0
        soc = np.concatenate([[battery.soc_mwh], simulate(battery, mw, np.zeros(len(mw))).soc_path])
        delta = np.diff(soc)
        done = np.where(delta > 0, delta / (0.5 * s), delta * s / 0.5)  # MW the battery executed
        clipped = np.abs(mw) - np.abs(done) > 1e-12
        if not clipped.any():
            return mw
        mw[clipped] = done[clipped]
    raise RuntimeError("LP schedule did not settle to an executable one")  # each pass only shrinks flows


class LPOptimiser:
    def __init__(self, conservative: bool = False):
        self.conservative = conservative

    def plan(self, quantiles: pd.DataFrame, battery: Battery) -> pd.DataFrame:
        times = quantiles.index
        p50 = quantiles["p50"].to_numpy(float)
        buy, sell = (
            (quantiles["p90"].to_numpy(float), quantiles["p10"].to_numpy(float))
            if self.conservative
            else (p50, p50)
        )

        c, d = _solve(buy, battery, exclusive=False, sell=sell)
        if np.minimum(c, d).max() > EPS:
            c, d = _solve(buy, battery, exclusive=True, sell=sell)
        mw = _executable(c - d, battery)

        spread = np.full(len(mw), np.nan)
        reason = [""] * len(mw)
        for rows, _ok, cycle_spread, gate_reason in self._cycles(mw, buy, sell, battery):
            for k in rows:
                spread[k] = cycle_spread
                verb = "charge" if mw[k] > 0 else "sell"
                reason[k] = f"{verb} in an LP cycle: {gate_reason}"

        s = np.sqrt(battery.rt_efficiency)
        stored = np.where(mw > 0, mw * 0.5 * s, 0.0)
        drawn = np.where(mw < 0, -mw * 0.5 / s, 0.0)
        soc_after = simulate(battery, mw, p50).soc_path
        for k in np.flatnonzero(mw == 0):
            spread[k], reason[k] = GreedyOptimiser._hold_reason(
                k, buy, stored, drawn, soc_after, battery, times
            )

        action = np.where(mw > 0, "charge", np.where(mw < 0, "discharge", "hold"))
        return pd.DataFrame(
            {"action": action, "mw": mw, "expected_spread": spread, "reason": reason}, index=times
        )

    @staticmethod
    def _cycles(mw, buy, sell, battery):
        """Yield (rows, ok, spread, reason) per cycle: charges, then the discharges before the next charge.
        Discharges before any charge sell energy stored before the horizon; their buy price is unknown,
        so they are gated on wear alone."""
        groups, charges, sells = [], [], []
        for k in np.flatnonzero(mw):
            if mw[k] > 0 and sells:  # first charge after a sale starts the next cycle
                groups.append((charges, sells))
                charges, sells = [], []
            (charges if mw[k] > 0 else sells).append(k)
        if charges or sells:
            groups.append((charges, sells))

        for charges, sells in groups:
            if not sells:  # charging for later than the horizon shows
                yield charges, True, np.nan, "energy kept for after this horizon"
                continue
            sell_price = np.average(sell[sells], weights=-mw[sells])
            if not charges:
                wear = battery.cycle_cost_gbp / battery.capacity_mwh
                yield (
                    sells,
                    sell_price > wear,
                    np.nan,
                    f"selling stored energy at {sell_price:.2f} > wear {wear:.2f}/MWh",
                )
                continue
            buy_price = np.average(buy[charges], weights=mw[charges])
            ok, cycle_spread, gate_reason = cost_gate(buy_price, sell_price, battery)
            yield charges + sells, ok, cycle_spread, gate_reason
