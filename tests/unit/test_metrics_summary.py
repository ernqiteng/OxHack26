"""metrics.summary: the honesty table, totals per strategy and share of perfect."""

from datetime import date

import pandas as pd
import pytest

from tempo.backtest.metrics import summary


def rows(strategy, pnls, perfects):
    return [
        {
            "run_id": "t",
            "week_start": date(2026, 2, 2 + 7 * i),
            "strategy": strategy,
            "pnl_gbp": p,
            "perfect_pnl_gbp": q,
            "pct_of_perfect": 100 * p / q,
            "regime": "calm",
        }
        for i, (p, q) in enumerate(zip(pnls, perfects, strict=True))
    ]


@pytest.fixture
def results():
    perfect = [500.0, 40.0]
    return pd.DataFrame(
        rows("perfect", perfect, perfect)
        + rows("simple_rule", [400.0, 40.0], perfect)
        + rows("persistence_greedy", [450.0, 0.0], perfect)
    )


def test_totals_and_share_of_perfect_by_hand(results):
    t = summary(results).set_index("strategy")
    assert t.loc["simple_rule", "pnl_gbp"] == 440.0
    assert t.loc["simple_rule", "pct_of_perfect"] == pytest.approx(100 * 440 / 540)
    # pounds-weighted: the flat week (perfect 40) barely moves the share, as description.md wants
    assert t.loc["persistence_greedy", "pct_of_perfect"] == pytest.approx(100 * 450 / 540)
    assert t.loc["perfect", "pct_of_perfect"] == 100.0
    assert (t.weeks == 2).all()


def test_rows_in_honesty_table_order_with_labels(results):
    t = summary(results)
    assert list(t.strategy) == ["simple_rule", "persistence_greedy", "perfect"]
    assert t.label.iloc[0].startswith("Simple rule")
    assert list(t.columns) == ["strategy", "label", "weeks", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"]


def test_unknown_strategy_kept_at_the_end(results):
    extra = pd.DataFrame(rows("my_experiment", [10.0, 1.0], [500.0, 40.0]))
    t = summary(pd.concat([results, extra]))
    assert t.strategy.iloc[-1] == "my_experiment" and t.label.iloc[-1] == "my_experiment"
