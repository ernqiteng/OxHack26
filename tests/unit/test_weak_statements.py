"""weak_statements: sentences carry the right percentages. Also by_regime and calibration, the other
honesty-panel data (docs/ernqi.md Phase 3 tasks 2 and 3)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tempo.backtest.metrics import by_regime, calibration, weak_statements

CALM, WINDY = date(2026, 2, 2), date(2026, 2, 9)


def results(pnl: dict, perfect=None):
    """pnl: {strategy: (calm_pnl, windy_pnl)}. Perfect is 200 on the calm week, 400 on the windy one."""
    perfect = perfect or (200.0, 400.0)
    rows = []
    for strategy, (calm, windy) in pnl.items():
        for week, regime, p, best in ((CALM, "calm", calm, perfect[0]), (WINDY, "windy", windy, perfect[1])):
            rows.append({"run_id": "t", "week_start": week, "strategy": strategy, "pnl_gbp": p,
                         "perfect_pnl_gbp": best, "pct_of_perfect": 100 * p / best, "regime": regime})
    return pd.DataFrame(rows)


@pytest.fixture
def known():
    # Tempo: calm 100 (50% of perfect), windy 300 (75%). Simple rule: calm 71, windy 120.
    # Persistence: calm 105, windy 150.
    return results({
        "simple_rule": (71.0, 120.0),
        "persistence_greedy": (105.0, 150.0),
        "tempo": (100.0, 300.0),
        "perfect": (200.0, 400.0),
    })


def test_close_baseline_sentence(known):
    assert "Simple rule reaches 71% of Tempo's profit on calm weeks." in weak_statements(known)


def test_baseline_beats_main_sentence(known):
    assert "Persistence beats Tempo on calm weeks: it makes 105% of Tempo's profit." in weak_statements(known)


def test_far_baselines_not_mentioned(known):
    lines = " ".join(weak_statements(known))
    assert "40%" not in lines  # simple rule on windy weeks: 120 / 300
    assert "all weeks" not in lines  # 191/400 = 48% and 255/400 = 64%, both below 70%


def test_regime_gap_sentence(known):
    assert "Tempo captures 75% of perfect on windy weeks but only 50% on calm weeks." in weak_statements(known)


def test_weakest_week_sentence(known):
    assert weak_statements(known)[-1] == "Weakest week for Tempo: week of 2026-02-02 (calm), 50% of perfect."


def test_losing_money_said_plainly():
    lines = weak_statements(results({"simple_rule": (10.0, 50.0), "tempo": (-20.0, 100.0)}))
    assert "Tempo loses money on calm weeks (£-20)." in lines


def test_without_tempo_grades_persistence():
    lines = weak_statements(results({"simple_rule": (95.0, 200.0), "persistence_greedy": (100.0, 210.0)}))
    assert "Simple rule reaches 95% of Persistence's profit on calm weeks." in lines


def test_no_main_strategy_no_lines():
    assert weak_statements(results({"simple_rule": (1.0, 2.0)})) == []


def test_by_regime_by_hand(known):
    t = by_regime(known).set_index(["strategy", "regime"])
    assert t.loc[("tempo", "calm"), "pct_of_perfect"] == pytest.approx(50.0)
    assert t.loc[("tempo", "windy"), "pct_of_perfect"] == pytest.approx(75.0)
    assert t.loc[("simple_rule", "calm"), "pnl_gbp"] == 71.0
    assert list(by_regime(known).strategy.unique()) == ["simple_rule", "persistence_greedy", "tempo", "perfect"]


def test_calibration_of_an_honest_band():
    """Actuals drawn from N(50, 10); bands at the true quantiles, so coverage is about 80%."""
    rng = np.random.default_rng(0)
    times = pd.date_range("2026-01-05", periods=20_000, freq="30min", tz="UTC")
    z = 1.2815515655446004  # N(0,1) 90th percentile
    forecasts = pd.DataFrame({"target_time": times, "p10": 50 - 10 * z, "p50": 50.0, "p90": 50 + 10 * z})
    actuals = pd.DataFrame({"bucket": times, "price": rng.normal(50, 10, len(times))})
    c = calibration(forecasts, actuals)
    assert c["n"] == len(times)
    assert c["coverage_p10_p90"] == pytest.approx(0.8, abs=0.01)
    assert c["quantiles"].observed.to_numpy() == pytest.approx([0.1, 0.5, 0.9], abs=0.01)
    assert c["reliability"].n.sum() == len(times)


def test_calibration_of_an_overconfident_band():
    times = pd.date_range("2026-01-05", periods=1_000, freq="30min", tz="UTC")
    actuals = pd.DataFrame({"bucket": times, "price": np.random.default_rng(1).normal(50, 10, len(times))})
    narrow = pd.DataFrame({"target_time": times, "p10": 49.0, "p50": 50.0, "p90": 51.0})
    assert calibration(narrow, actuals)["coverage_p10_p90"] < 0.2


def test_calibration_without_matches():
    times = pd.date_range("2026-01-05", periods=3, freq="30min", tz="UTC")
    forecasts = pd.DataFrame({"target_time": times, "p10": 1.0, "p50": 2.0, "p90": 3.0})
    c = calibration(forecasts, pd.DataFrame({"bucket": times + pd.Timedelta(days=1), "price": 2.0}))
    assert c["n"] == 0 and c["coverage_p10_p90"] is None
