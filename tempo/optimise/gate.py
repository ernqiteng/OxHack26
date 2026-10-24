"""cost_gate(buy_price, sell_price, battery) -> (ok, expected_spread, reason). Holds unless a cycle pays.

Owner: Ernqi. See docs/ernqi.md Phase 1 task 2.

Per MWh bought, the battery sells eff MWh back (sqrt(eff) in, sqrt(eff) out), and wear is charged on
MWh sold, exactly as simulate() does. So a buy/sell pair makes money iff

    sell - buy  >  (1 - eff) * sell  +  eff * cycle_cost_gbp / capacity_mwh
    spread         efficiency loss      degradation

which is eff * sell - buy > eff * cycle cost per MWh sold. ernqi.md writes the right-hand side as the
full cycle cost per MWh (10.0 by default); charging it on the eff MWh actually sold (9.0) keeps
"ok" identical to "simulate() shows a profit".
"""

from tempo.sim.battery import Battery

TOLERANCE_GBP = 1e-9  # a spread exactly at the threshold is not worth cycling for


def cost_gate(buy_price: float, sell_price: float, battery: Battery) -> tuple[bool, float, str]:
    eff = battery.rt_efficiency
    spread = sell_price - buy_price
    loss = (1 - eff) * sell_price
    degradation = eff * battery.cycle_cost_gbp / battery.capacity_mwh
    cost = loss + degradation
    ok = spread - cost > TOLERANCE_GBP
    reason = (
        f"spread {spread:.2f} {'>' if ok else '<='} cost {cost:.2f} "
        f"(efficiency loss {loss:.2f} at {1 - eff:.0%} + degradation {degradation:.2f}/MWh)"
    )
    return ok, spread, reason
