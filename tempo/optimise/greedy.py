"""GreedyOptimiser.plan(quantiles, battery): cheapest-vs-dearest pairing under limits, cost-gated.

Owner: Ernqi. See docs/ernqi.md Phase 1 task 3.

On p50 only. Works in MWh stored in the battery. Each period can store up to power_mw * 0.5 * sqrt(eff)
(charging) or release up to power_mw * 0.5 / sqrt(eff) (discharging), never both. Repeatedly take the
(buy period, later sell period) pair with the largest net value per MWh, as cost_gate counts it,
    eff * sell - buy - eff * cycle_cost_gbp / capacity_mwh     (per MWh bought)
and move as much energy between them as fits: the charge room at the buy, the discharge room at the
sell, and the space left in the battery between the two. Energy already stored at the start counts as
a free source (it was paid for earlier), so it is sold when a period pays more than the wear.
Pairs that fail cost_gate are never used; stop when no pair can move any energy.
"""

import numpy as np
import pandas as pd

from tempo.optimise.gate import cost_gate
from tempo.sim.battery import Battery

STOCK = -1  # pseudo buy period for energy stored before the horizon
EPS = 1e-9


class GreedyOptimiser:
    def plan(self, quantiles: pd.DataFrame, battery: Battery) -> pd.DataFrame:
        p = quantiles["p50"].to_numpy(dtype=float)
        times = quantiles.index
        n = len(p)
        eff, s = battery.rt_efficiency, np.sqrt(battery.rt_efficiency)
        wear = battery.cycle_cost_gbp / battery.capacity_mwh  # per MWh sold

        charge_room = np.full(n, battery.power_mw * 0.5 * s)  # MWh stored
        discharge_room = np.full(n, battery.power_mw * 0.5 / s)  # MWh drawn
        stored = np.zeros(n)
        drawn = np.zeros(n)
        soc_after = np.full(n, battery.soc_mwh)
        first_pair: dict[int, tuple[int, int]] = {}

        def value(i, j):  # per MWh bought; the starting stock costs nothing to "buy"
            return eff * p[j] - (0.0 if i == STOCK else p[i]) - eff * wear

        def passes(i, j):
            return p[j] > wear if i == STOCK else cost_gate(p[i], p[j], battery)[0]

        while True:
            best = None
            sells = [j for j in range(n) if discharge_room[j] > EPS and stored[j] == 0]
            buys = [STOCK] + [i for i in range(n) if charge_room[i] > EPS and drawn[i] == 0]
            for j in sells:
                for i in buys:
                    if i >= j:
                        break
                    v = value(i, j)
                    if best is not None and v <= best[0]:
                        continue
                    if not passes(i, j):
                        continue
                    if i == STOCK:  # SoC drops from j on and must stay >= 0
                        amount = min(discharge_room[j], soc_after[j:].min())
                    else:  # SoC rises between i and j and must stay <= capacity
                        space = battery.capacity_mwh - soc_after[i:j].max()
                        amount = min(charge_room[i], discharge_room[j], space)
                    if amount > EPS:
                        best = (v, i, j, amount)
            if best is None:
                break
            _, i, j, amount = best
            if i == STOCK:
                soc_after[j:] -= amount
            else:
                charge_room[i] -= amount
                stored[i] += amount
                soc_after[i:j] += amount
                first_pair.setdefault(i, (i, j))
            discharge_room[j] -= amount
            drawn[j] += amount
            first_pair.setdefault(j, (i, j))

        mw = stored / (0.5 * s) - drawn * s / 0.5
        mw[np.abs(mw) < EPS] = 0.0
        spread = np.full(n, np.nan)
        reason = [""] * n
        for k in range(n):
            if k in first_pair and mw[k] != 0:
                spread[k], reason[k] = self._trade_reason(k, *first_pair[k], p, battery, times, wear)
            else:
                spread[k], reason[k] = self._hold_reason(k, p, stored, drawn, soc_after, battery, times)

        action = np.where(mw > 0, "charge", np.where(mw < 0, "discharge", "hold"))
        return pd.DataFrame(
            {"action": action, "mw": mw, "expected_spread": spread, "reason": reason}, index=times
        )

    @staticmethod
    def _trade_reason(k, i, j, p, battery, times, wear):
        if i == STOCK:
            return p[j], f"sell stored energy: price {p[j]:.2f} > wear {wear:.2f}/MWh"
        _, pair_spread, gate_reason = cost_gate(p[i], p[j], battery)
        if k == i:
            return pair_spread, f"charge for sale at {_hhmm(times[j])}: {gate_reason}"
        return pair_spread, f"sell energy bought at {_hhmm(times[i])}: {gate_reason}"

    @staticmethod
    def _hold_reason(k, p, stored, drawn, soc_after, battery, times):
        """Best partner for period k, as a buy or as a sell, and why no energy moved."""
        n = len(p)
        candidates = [(k, j) for j in range(k + 1, n) if stored[j] == 0] + [
            (i, k) for i in range(k) if drawn[i] == 0
        ]
        if not candidates:
            return np.nan, "hold: no other free period in the horizon to pair with"
        i, j = max(candidates, key=lambda ij: battery.rt_efficiency * p[ij[1]] - p[ij[0]])
        ok, pair_spread, gate_reason = cost_gate(p[i], p[j], battery)
        if not ok:
            return pair_spread, f"hold: {gate_reason}"
        peak = soc_after[i:j].max()
        if peak >= battery.capacity_mwh - 1e-6:
            return pair_spread, (
                f"hold: battery full between {_hhmm(times[i])} and {_hhmm(times[j])} "
                f"(SoC {peak:.2f} of {battery.capacity_mwh:.2f} MWh)"
            )
        return pair_spread, f"hold: better-paying periods already use the battery around {_hhmm(times[k])}"


def _hhmm(t) -> str:
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)
