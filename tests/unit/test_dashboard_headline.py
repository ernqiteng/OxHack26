"""The dashboard headlines one strategy everywhere: tempo (LightGBM + greedy), which the live decider runs.

Known answer: the latest Tiger run db-20261024T202144Z, 100 unseen weeks, pooled pnl / perfect pnl:
simple rule 33.1%, persistence 52.9%, tempo 66.4%, tempo_lp 68.3%. Before this, the header and the honesty
sentence took the LAST tempo-prefixed row (tempo_lp, shown by its raw id) while the "where it's weak" lines
described tempo, so the page quoted two different strategies.
"""

import pandas as pd

from tempo.backtest.metrics import HEADLINE_STRATEGY, _main_strategy, weak_statements
from tempo.dashboard import ui
from tempo.dashboard.data import DbSource, calibration_sentence, headline_name, main_strategy_row

PERFECT = 88388.0
PNL = {"simple_rule": 29265.0, "persistence_greedy": 46798.0, "tempo": 58711.0, "tempo_lp": 60391.0}


def latest_run_summary() -> pd.DataFrame:
    """What DbSource.backtest_summary() returns for the latest run, without a database."""
    raw = pd.DataFrame(
        {
            "strategy": [
                "perfect",
                "tempo_lp",
                "simple_rule",
                "tempo",
                "persistence_greedy",
            ],  # SQL order: any
            "pnl_gbp": [
                PERFECT,
                PNL["tempo_lp"],
                PNL["simple_rule"],
                PNL["tempo"],
                PNL["persistence_greedy"],
            ],
        }
    )
    raw["pct_of_perfect"] = 100 * raw.pnl_gbp / PERFECT
    src = DbSource(conn=None)
    src._df = lambda sql, params=(): raw.copy()  # noqa: SLF001 - stub the one query
    return src.backtest_summary()


def test_headline_is_the_strategy_live_runs():
    assert HEADLINE_STRATEGY == "tempo"


def test_summary_labels_and_orders_all_five():
    s = latest_run_summary()
    assert s.strategy.tolist() == [
        "Simple rule (charge 01:00-05:00, sell 17:00-19:00)",
        "Persistence forecast + same optimiser",
        "Tempo (LightGBM forecast + same optimiser)",
        "Tempo LP (LightGBM forecast + LP optimiser)",
        "Perfect knowledge of the future",
    ]
    assert s.pct_of_perfect.tolist() == [33.1, 52.9, 66.4, 68.3, 100.0]
    assert "tempo_lp" not in s.strategy.tolist()  # never a raw id on screen


def test_header_and_honesty_sentence_name_tempo_66_4():
    main = main_strategy_row(latest_run_summary())
    assert main.strategy == "Tempo (LightGBM forecast + same optimiser)"
    assert main.pct_of_perfect == 66.4
    assert headline_name(main) == "Tempo"  # the word both sentences start with


def test_ladder_highlights_only_tempo():
    s = latest_run_summary()
    main = main_strategy_row(s)
    bars = ui.ladder(s, main_prefix=main.strategy).data  # Altair lifts shared data to the layer chart
    assert bars.loc[bars.is_main, "strategy"].tolist() == ["Tempo (LightGBM forecast + same optimiser)"]


def test_weak_statements_describe_the_same_strategy():
    weeks = pd.date_range("2025-01-06", periods=4, freq="7D").date
    rows = []
    for i, week in enumerate(weeks):
        regime = "windy" if i % 2 else "calm"
        for strategy, pnl in {**PNL, "perfect": PERFECT}.items():
            rows.append(
                {"run_id": "r", "week_start": week, "strategy": strategy, "pnl_gbp": pnl / 4,
                 "perfect_pnl_gbp": PERFECT / 4, "pct_of_perfect": 100 * pnl / PERFECT, "regime": regime}
            )  # fmt: skip
    lines = weak_statements(pd.DataFrame(rows))
    assert lines and all("Tempo (LP)" not in line for line in lines)
    assert any("Tempo" in line for line in lines)
    assert _main_strategy({"tempo_lp", "tempo", "persistence_greedy"}) == "tempo"


def test_fallbacks_without_the_headline_row():
    s = latest_run_summary()
    no_tempo = s[~s.strategy.str.startswith("Tempo (")]
    assert headline_name(main_strategy_row(no_tempo)) == "Tempo LP"  # LP variant before the baselines
    baselines = s[~s.strategy.str.startswith("Tempo")]
    assert main_strategy_row(baselines).pct_of_perfect == 52.9  # best non-perfect row
    assert main_strategy_row(s[s.strategy.str.startswith("Perfect")]) is None


def test_calibration_sentence_states_a_verdict():
    """Known answer from docs/a.md: 384 settled live forecasts, 77% inside the p10-p90 band, 80% target."""
    live = calibration_sentence(384, 0.77)
    assert live.startswith(
        "384 settled live forecasts: the p10–p90 band held 77% of actual prices against an 80%"
    )
    assert "slightly overconfident (the band is too narrow)" in live
    assert "p50 forecast only" in live
    assert "overconfident (the band is too narrow)" in calibration_sentence(
        1344, 0.63
    )  # the training holdout
    assert "slightly" not in calibration_sentence(1344, 0.63)
    assert "about right" in calibration_sentence(500, 0.80)
    assert "about right" in calibration_sentence(500, 0.815)
    assert "under-confident (the band is too wide)" in calibration_sentence(500, 0.86)
