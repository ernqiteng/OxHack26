"""Self-grade on synthetic cycles with known timing errors. docs/ernqi.md Phase 3 tests."""

import numpy as np
import pytest

from tempo.audit.selfgrade import best_shift, grade_cycles, self_grade
from tempo.audit.shifts import ReplayError, shift_schedule
from tempo.backtest.walkforward import prices_hh_from_grid_raw
from tempo.optimise.perfect import perfect_foresight
from tempo.sim.battery import Battery, simulate
from tests.fixtures.synthetic import make_synthetic_market

N_DAYS = 10


@pytest.fixture(scope="module")
def days():
    """Ten synthetic days, each with its perfect plan: the best timing there is."""
    prices = prices_hh_from_grid_raw(make_synthetic_market(days=N_DAYS)).price.to_numpy().reshape(N_DAYS, 48)
    return [(p, perfect_foresight(p, Battery()).mw.to_numpy()) for p in prices]


def replay_for(days, late_by: dict[int, int]):
    """replay(cycle, shift): the cycle's plan, made late_by[cycle] periods late, then shifted, at actual prices."""
    def replay(cycle, shift):
        prices, plan = days[cycle]
        decided = shift_schedule(plan, late_by.get(cycle, 0))
        return simulate(Battery(), shift_schedule(decided, shift), prices).pnl_gbp
    return replay


def test_late_by_one_on_half_the_cycles(days):
    late = {c: 1 for c in range(0, N_DAYS, 2)}
    grade = grade_cycles(range(N_DAYS), replay_for(days, late))
    assert grade["n_cycles"] == N_DAYS
    assert grade["pct_within_one_period"] == 1.0
    assert grade["mean_cost_of_mistiming_gbp"] > 0


def test_late_by_two_on_all_cycles(days):
    late = {c: 2 for c in range(N_DAYS)}
    grade = grade_cycles(range(N_DAYS), replay_for(days, late))
    assert grade["pct_within_one_period"] == 0.0
    assert grade["mean_cost_of_mistiming_gbp"] > 0


def test_perfect_timing_costs_nothing(days):
    grade = grade_cycles(range(N_DAYS), replay_for(days, {}))
    assert grade["pct_within_one_period"] == 1.0
    assert grade["mean_cost_of_mistiming_gbp"] == pytest.approx(0.0, abs=1e-9)


def test_unsettled_cycles_are_skipped(days):
    replay = replay_for(days, {})

    def flaky(cycle, shift):
        if cycle == 3:
            raise ReplayError("periods have no actual price yet")
        return replay(cycle, shift)

    assert grade_cycles(range(5), flaky)["n_cycles"] == 4


def test_other_errors_are_not_swallowed(days):
    def broken(cycle, shift):
        raise ValueError("bug")

    with pytest.raises(ValueError):
        grade_cycles([0], broken)


def test_no_cycles_gives_none():
    assert grade_cycles([], lambda c, s: 0.0) == {
        "pct_within_one_period": None, "n_cycles": 0, "mean_cost_of_mistiming_gbp": None,
    }


def test_best_shift_ties_prefer_smallest_move():
    assert best_shift({-2: 5.0, -1: 5.0, 0: 5.0, 1: 5.0, 2: 5.0}) == 0
    assert best_shift({-2: 1.0, -1: 7.0, 0: 3.0, 1: 7.0, 2: 1.0}) == -1


class FakeCursor:
    def __init__(self, ids):
        self.ids, self.sql = ids, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return [(i,) for i in self.ids]


class FakeConn:
    def __init__(self, ids):
        self.cur = FakeCursor(ids)

    def cursor(self):
        return self.cur


def test_self_grade_calls_replay_shift_with_its_own_run_ids(days):
    conn, calls = FakeConn([0, 1]), []
    replay = replay_for(days, {})

    def fake_replay_shift(c, decision_id, shift, run_id):
        calls.append(run_id)
        return replay(decision_id, shift)

    grade = self_grade(conn, since=None, replay_shift=fake_replay_shift)
    assert grade["n_cycles"] == 2
    assert calls[:5] == [f"selfgrade-0-{s}" for s in (-2, -1, 0, 1, 2)]
    assert "run_id = %s" in conn.cur.sql and conn.cur.params[0] == "live"
