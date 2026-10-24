"""DbSource reads real rows and runs a real in-process audit on the local DB."""

from datetime import date

import numpy as np

from tempo.dashboard.data import DbSource

from .conftest import day_prices, targets


def test_dbsource_reads_live_rows_and_audits(market):
    mw = np.zeros(48)
    mw[2:6], mw[34:38] = 1.0, -1.0
    market.prices(targets(), day_prices())
    did = market.decisions(mw)
    src = DbSource(market.conn)

    prices = src.recent_prices(24)
    assert len(prices) == 48 and "recent_prices" not in src.notes
    sched = src.todays_schedule()
    assert len(sched) == 48 and set(sched.action) == {"charge", "discharge", "hold"}
    assert src.latest_hold() is not None
    decisions = src.recent_decisions(50)
    assert "recent_decisions" not in src.notes and did in set(decisions.decision_id)

    rows = src.run_audit(did)
    assert sorted(rows["shift"]) == [-2, -1, 0, 1, 2]
    assert rows.loc[rows["shift"] == 0, "pnl_delta_gbp"].iloc[0] == 0.0
    assert rows["error"].isna().all()


def test_backtest_summary_from_table(market):
    with market.conn.cursor() as cur:
        for strat, pnl in [("simple_rule", 50.0), ("tempo", 80.0), ("perfect", 100.0)]:
            for wk, regime in [(date(2026, 1, 5), "calm"), (date(2026, 1, 12), "windy")]:
                cur.execute(
                    "INSERT INTO backtest_results VALUES ('bt-1', %s, %s, %s, 100, %s, %s)",
                    (wk, strat, pnl, pnl, regime),
                )
    src = DbSource(market.conn)
    summary = src.backtest_summary()
    assert "backtest_summary" not in src.notes
    assert summary.pct_of_perfect.tolist() == [50.0, 80.0, 100.0]
    assert summary.strategy.iloc[-1].startswith("Perfect")
    assert len(src.backtest_by_regime()) == 6


def test_weak_points_come_from_backtest_rows(market):
    with market.conn.cursor() as cur:
        for wk, regime in [(date(2026, 1, 5), "calm"), (date(2026, 1, 12), "windy")]:
            for strat, pnl in [("simple_rule", 90.0), ("persistence_greedy", 95.0), ("perfect", 100.0)]:
                cur.execute(
                    "INSERT INTO backtest_results VALUES ('bt-2', %s, %s, %s, 100, %s, %s)",
                    (wk, strat, pnl, pnl, regime),
                )
    src = DbSource(market.conn)
    lines = src.weak_points()
    assert "weak_points" not in src.notes
    assert lines and all(isinstance(line, str) and line for line in lines)
