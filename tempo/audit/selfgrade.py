"""self_grade(conn, since) -> pct_within_one_period, n_cycles, mean_cost_of_mistiming_gbp.

Owner: Ernqi (called by Ayo). See docs/ernqi.md Phase 3 task 1.

For every completed cycle, replay it shifted by -2..+2 periods at actual prices and see which shift
would have made the most money. If the best shift is -1, 0 or +1, Tempo's timing was within one
period of the best it could have done.

A "cycle" here is one 'live' decision batch (the 48 rows written together by run_decision) that both
charges and discharges, because replay_shift shifts a whole batch. A batch is completed once every
period has an actual price; replay_shift raises ReplayError until then, and those batches are skipped.

    pct_within_one_period       share of cycles whose best shift is in {-1, 0, +1}   (0.0 to 1.0)
    n_cycles                    cycles graded
    mean_cost_of_mistiming_gbp  mean of (best shift's pnl - actual pnl), >= 0
"""

from collections.abc import Callable, Iterable
from datetime import datetime

SHIFTS = (-2, -1, 0, 1, 2)
LIVE_RUN_ID = "live"


def best_shift(pnl_by_shift: dict[int, float]) -> int:
    """Shift with the highest pnl; ties go to the smallest |shift| (then the earlier one)."""
    return max(pnl_by_shift, key=lambda s: (round(pnl_by_shift[s], 9), -abs(s), -s))


def grade_cycles(cycle_ids: Iterable[int], replay: Callable[[int, int], float]) -> dict:
    """Pure grading: replay(cycle_id, shift) -> pnl_gbp. Cycles whose replay raises are skipped."""
    within, costs = [], []
    for cycle_id in cycle_ids:
        try:
            pnl = {s: replay(cycle_id, s) for s in SHIFTS}
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "ReplayError":  # not settled yet, or prices missing
                continue
            raise
        best = best_shift(pnl)
        within.append(abs(best) <= 1)
        costs.append(pnl[best] - pnl[0])
    n = len(within)
    return {
        "pct_within_one_period": sum(within) / n if n else None,
        "n_cycles": n,
        "mean_cost_of_mistiming_gbp": sum(costs) / n if n else None,
    }


def completed_cycle_ids(conn, since: datetime) -> list[int]:
    """One decision_id per 'live' batch decided since `since` that both charges and discharges."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT min(decision_id) FROM decisions
               WHERE run_id = %s AND decided_at >= %s
               GROUP BY decided_at
               HAVING bool_or(action = 'charge') AND bool_or(action = 'discharge')
               ORDER BY min(decided_at)""",
            (LIVE_RUN_ID, since),
        )
        return [row[0] for row in cur.fetchall()]


def selfgrade_run_id(decision_id: int, shift: int) -> str:
    return f"selfgrade-{decision_id}-{shift}"


def self_grade(conn, since: datetime, replay_shift=None) -> dict:
    """Grade every completed live cycle since `since` with Ayo's in-process replay_shift.
    Replays write battery_state under selfgrade-<decision_id>-<shift>; replay_shift clears its own
    window first, so re-running the grade is safe."""
    if replay_shift is None:
        from tempo.audit.shifts import replay_shift
    return grade_cycles(
        completed_cycle_ids(conn, since),
        lambda decision_id, shift: replay_shift(conn, decision_id, shift, selfgrade_run_id(decision_id, shift)),
    )
