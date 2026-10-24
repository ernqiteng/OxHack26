"""summary(), pct_of_perfect, calibration(), by_regime(), weak_statements().

Owner: Ernqi. See docs/ernqi.md.

summary() is the honesty table in docs/description.md section 3, Layer 3: money made per strategy and the
share of perfect foresight captured. The share is total pnl / total perfect pnl over all test weeks, so a
volatile week counts for more than a flat one, exactly as the pounds do.
"""

import pandas as pd

from tempo.backtest.walkforward import pct_of_perfect

STRATEGY_ORDER = ["simple_rule", "persistence_greedy", "tempo", "tempo_lp", "perfect"]
LABELS = {
    "simple_rule": "Simple rule (charge 1am to 5am, sell 5pm to 7pm)",
    "persistence_greedy": "Persistence forecast + same optimiser",
    "tempo": "Tempo (LightGBM forecast + same optimiser)",
    "tempo_lp": "Tempo (LightGBM forecast + LP optimiser)",
    "perfect": "Perfect knowledge of the future",
}


def summary(results: pd.DataFrame) -> pd.DataFrame:
    """One row per strategy: label, weeks, pnl_gbp, perfect_pnl_gbp, pct_of_perfect. Takes backtest_results rows."""
    totals = results.groupby("strategy").agg(
        weeks=("week_start", "nunique"), pnl_gbp=("pnl_gbp", "sum"), perfect_pnl_gbp=("perfect_pnl_gbp", "sum")
    )
    totals["pct_of_perfect"] = [pct_of_perfect(r.pnl_gbp, r.perfect_pnl_gbp) for r in totals.itertuples()]
    order = [s for s in STRATEGY_ORDER if s in totals.index] + sorted(set(totals.index) - set(STRATEGY_ORDER))
    out = totals.loc[order].reset_index()
    out.insert(1, "label", out.strategy.map(LABELS).fillna(out.strategy))
    return out[["strategy", "label", "weeks", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"]]
