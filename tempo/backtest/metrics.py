"""summary(), pct_of_perfect, calibration(), by_regime(), weak_statements().

Owner: Ernqi. See docs/ernqi.md.

summary() is the honesty table in docs/description.md section 3, Layer 3: money made per strategy and the
share of perfect foresight captured. The share is total pnl / total perfect pnl over all test weeks, so a
volatile week counts for more than a flat one, exactly as the pounds do.

by_regime() and calibration() are the dashboard's regime breakdown and calibration chart (Phase 3 task 2);
weak_statements() writes the "where it's weak" lines (Phase 3 task 3). All return plain data.
"""

import pandas as pd

from tempo.backtest.walkforward import pct_of_perfect

STRATEGY_ORDER = ["simple_rule", "persistence_greedy", "tempo", "tempo_lp", "perfect"]
# The strategy the dashboard headlines and the weak statements describe: LightGBM + greedy, which is what the
# live decider runs (scripts/decide.py defaults to GreedyOptimiser). tempo_lp is shown as the LP variant.
HEADLINE_STRATEGY = "tempo"
LABELS = {
    "simple_rule": "Simple rule (charge 1am to 5am, sell 5pm to 7pm)",
    "persistence_greedy": "Persistence forecast + same optimiser",
    "tempo": "Tempo (LightGBM forecast + same optimiser)",
    "tempo_lp": "Tempo (LightGBM forecast + LP optimiser)",
    "perfect": "Perfect knowledge of the future",
    "tempo_lp_safe": "Tempo (LP, conservative: buy at p90, sell at p10)",
    "tempo_lp_safe_cal": "Tempo (LP, conservative, recalibrated band)",
}


def summary(results: pd.DataFrame) -> pd.DataFrame:
    """One row per strategy: label, weeks, pnl_gbp, perfect_pnl_gbp, pct_of_perfect.
    Takes backtest_results rows."""
    totals = results.groupby("strategy").agg(
        weeks=("week_start", "nunique"),
        pnl_gbp=("pnl_gbp", "sum"),
        perfect_pnl_gbp=("perfect_pnl_gbp", "sum"),
    )
    totals["pct_of_perfect"] = [pct_of_perfect(r.pnl_gbp, r.perfect_pnl_gbp) for r in totals.itertuples()]
    order = [s for s in STRATEGY_ORDER if s in totals.index] + sorted(set(totals.index) - set(STRATEGY_ORDER))
    out = totals.loc[order].reset_index()
    out.insert(1, "label", out.strategy.map(LABELS).fillna(out.strategy))
    return out[["strategy", "label", "weeks", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"]]


def by_regime(results: pd.DataFrame) -> pd.DataFrame:
    """One row per (strategy, regime): weeks, pnl_gbp, perfect_pnl_gbp, pct_of_perfect.
    Same maths as summary()."""
    rows = []
    for (strategy, regime), g in results.dropna(subset=["regime"]).groupby(["strategy", "regime"]):
        pnl, best = g.pnl_gbp.sum(), g.perfect_pnl_gbp.sum()
        rows.append(
            {
                "strategy": strategy,
                "regime": regime,
                "weeks": g.week_start.nunique(),
                "pnl_gbp": pnl,
                "perfect_pnl_gbp": best,
                "pct_of_perfect": pct_of_perfect(pnl, best),
            }
        )
    out = pd.DataFrame(
        rows, columns=["strategy", "regime", "weeks", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"]
    )
    rank = {s: i for i, s in enumerate(STRATEGY_ORDER)}
    return out.sort_values(
        ["strategy", "regime"],
        key=lambda c: c.map(rank).fillna(len(rank)) if c.name == "strategy" else c,
        ignore_index=True,
    )


def calibration(forecasts: pd.DataFrame, actuals: pd.DataFrame, bins: int = 10) -> dict:
    """How honest the forecast bands are.

    forecasts: target_time, p10, p50, p90. actuals: prices_hh (bucket, price).

    Returns
        n                 forecasts with an actual price
        coverage_p10_p90  share of actuals inside [p10, p90]; 0.8 is honest for a p10-p90 band
        quantiles         DataFrame quantile, nominal, observed: share of actuals at or below each forecast
                          quantile (an honest p10 has 10% of actuals below it)
        reliability       DataFrame by p50 decile: bin, n, mean_p50, mean_actual, coverage, for the chart
    """
    joined = forecasts.merge(
        actuals.rename(columns={"bucket": "target_time", "price": "actual"}), on="target_time"
    )
    joined = joined.dropna(subset=["p10", "p50", "p90", "actual"])
    n = len(joined)
    empty = {
        "n": 0,
        "coverage_p10_p90": None,
        "quantiles": pd.DataFrame(columns=["quantile", "nominal", "observed"]),
        "reliability": pd.DataFrame(columns=["bin", "n", "mean_p50", "mean_actual", "coverage"]),
    }
    if n == 0:
        return empty
    inside = (joined.actual >= joined.p10) & (joined.actual <= joined.p90)
    quantiles = pd.DataFrame(
        {
            "quantile": ["p10", "p50", "p90"],
            "nominal": [0.1, 0.5, 0.9],
            "observed": [(joined.actual <= joined[q]).mean() for q in ("p10", "p50", "p90")],
        }
    )
    joined = joined.assign(
        inside=inside, bin=pd.qcut(joined.p50.rank(method="first"), min(bins, n), labels=False)
    )
    reliability = (
        joined.groupby("bin")
        .agg(
            n=("actual", "size"),
            mean_p50=("p50", "mean"),
            mean_actual=("actual", "mean"),
            coverage=("inside", "mean"),
        )
        .reset_index()
    )
    return {"n": n, "coverage_p10_p90": inside.mean(), "quantiles": quantiles, "reliability": reliability}


SHORT_NAMES = {
    "simple_rule": "Simple rule",
    "persistence_greedy": "Persistence",
    "tempo": "Tempo",
    "tempo_lp": "Tempo (LP)",
    "perfect": "Perfect foresight",
}


def _main_strategy(strategies) -> str | None:
    for s in (HEADLINE_STRATEGY, "tempo_lp", "persistence_greedy"):
        if s in strategies:
            return s
    return None


def weak_statements(results: pd.DataFrame, close: float = 0.7, regime_gap_points: float = 5.0) -> list[str]:
    """Plain-English limits of the main strategy (Tempo if present, else Tempo LP, else persistence), from
    backtest_results rows. Says where a simpler baseline gets close to it (>= `close` of its profit) or beats
    it, overall and per regime; where it loses money; how far apart its regimes are; and its weakest week."""
    main = _main_strategy(set(results.strategy))
    if main is None:
        return []
    name = lambda s: SHORT_NAMES.get(s, s)  # noqa: E731
    lines = []
    regimes = sorted(results.regime.dropna().unique())
    scopes = [("all weeks", results)] + [(f"{r} weeks", results[results.regime == r]) for r in regimes]

    for scope, df in scopes:
        main_pnl = df[df.strategy == main].pnl_gbp.sum()
        if main_pnl <= 0:
            lines.append(f"{name(main)} loses money on {scope} (£{main_pnl:,.0f}).")
            continue
        for base in ("simple_rule", "persistence_greedy"):
            if base == main or base not in set(df.strategy):
                continue
            ratio = df[df.strategy == base].pnl_gbp.sum() / main_pnl
            if ratio > 1:
                lines.append(
                    f"{name(base)} beats {name(main)} on {scope}: "
                    f"it makes {ratio:.0%} of {name(main)}'s profit."
                )
            elif ratio >= close:
                lines.append(f"{name(base)} reaches {ratio:.0%} of {name(main)}'s profit on {scope}.")

    regime_pct = by_regime(results).query("strategy == @main").set_index("regime").pct_of_perfect
    if len(regime_pct) >= 2 and regime_pct.max() - regime_pct.min() >= regime_gap_points:
        hi, lo = regime_pct.idxmax(), regime_pct.idxmin()
        lines.append(
            f"{name(main)} captures {regime_pct[hi]:.0f}% of perfect on {hi} weeks "
            f"but only {regime_pct[lo]:.0f}% on {lo} weeks."
        )

    weeks = results[results.strategy == main]
    if len(weeks) >= 2:
        worst = weeks.loc[weeks.pct_of_perfect.idxmin()]
        regime = f" ({worst.regime})" if isinstance(worst.regime, str) else ""
        lines.append(
            f"Weakest week for {name(main)}: week of {worst.week_start}{regime}, "
            f"{worst.pct_of_perfect:.0f}% of perfect."
        )
    return lines
