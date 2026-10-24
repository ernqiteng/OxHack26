"""run_decision on a synthetic month: 48 decisions + 48 forecasts per batch, decided_at == now, run_id set,
holds carry a reason, forecast_id links each decision to its forecast, the returned id is the first period,
a re-run at the same time replaces the batch, and Ayo's replay/audit works on the result."""

from datetime import timedelta

import pytest

from tempo.audit.orchestrator import run_audit
from tempo.audit.shifts import replay_shift
from tempo.decide.engine import run_decision
from tempo.forecast.dataset import decision_times, make_training_set
from tempo.forecast.lgbm import LightGBMQuantileForecaster
from tempo.optimise.greedy import GreedyOptimiser
from tempo.optimise.lp import LPOptimiser
from tests.db.helpers import MONDAY, clean, market

DAYS = 30
NOW = MONDAY + timedelta(days=20, hours=12)  # mid-month: prices exist for the whole horizon


@pytest.fixture
def synthetic_month(db_conn):
    market(db_conn, MONDAY, DAYS)
    yield db_conn
    clean(db_conn, MONDAY, MONDAY + timedelta(days=DAYS))


@pytest.fixture
def model(synthetic_month):
    X, y = make_training_set(
        synthetic_month,
        decision_times(MONDAY + timedelta(days=9), MONDAY + timedelta(days=18), timedelta(hours=12)),
    )
    m = LightGBMQuantileForecaster(n_estimators=40)
    m.fit(X, y)
    return m


def fetch(conn, table, decided_at, run_id):
    cols = (
        "decision_id, target_time, action, mw, reason, forecast_id"
        if table == "decisions"
        else "forecast_id, target_time, p10, p50, p90, model"
    )
    return conn.execute(
        f"SELECT {cols} FROM {table} WHERE decided_at = %s AND run_id = %s ORDER BY target_time",  # noqa: S608
        (decided_at, run_id),
    ).fetchall()


@pytest.mark.parametrize("optimiser", [GreedyOptimiser(), LPOptimiser()])
def test_run_decision_writes_a_full_batch(synthetic_month, model, optimiser):
    conn = synthetic_month
    did = run_decision(conn, NOW, model, optimiser, run_id="live")

    decisions = fetch(conn, "decisions", NOW, "live")
    forecasts = fetch(conn, "forecasts", NOW, "live")
    assert len(decisions) == 48 and len(forecasts) == 48
    assert decisions[0][0] == did  # first period's id is returned
    assert decisions[0][1] == NOW + timedelta(minutes=30)
    assert all(a in ("charge", "discharge", "hold") for _, _, a, *_ in decisions)
    for _, _, action, mw, reason, forecast_id in decisions:
        assert (action == "charge") == (mw > 0) and (action == "discharge") == (mw < 0)
        assert reason and reason.strip(), "every row explains itself"
        assert forecast_id is not None
    assert {d[5] for d in decisions} == {f[0] for f in forecasts}  # each decision links to a forecast row
    assert all(p10 <= p50 <= p90 for *_, p10, p50, p90, _ in forecasts)
    assert forecasts[0][5] == "LightGBMQuantileForecaster"
    actions = {a for _, _, a, *_ in decisions}
    assert "charge" in actions and "discharge" in actions, "a synthetic day with a 40 GBP spread must trade"


def test_rerun_same_time_replaces_not_duplicates(synthetic_month, model):
    conn = synthetic_month
    first = run_decision(conn, NOW, model, GreedyOptimiser())
    second = run_decision(conn, NOW, model, GreedyOptimiser())
    assert second != first
    assert len(fetch(conn, "decisions", NOW, "live")) == 48
    assert len(fetch(conn, "forecasts", NOW, "live")) == 48


def test_ayo_replay_and_audit_work_on_the_batch(synthetic_month, model):
    conn = synthetic_month
    did = run_decision(conn, NOW, model, GreedyOptimiser())
    pnl = replay_shift(conn, did, 0, "test-replay")
    assert isinstance(pnl, float)
    rows = run_audit(conn, did, mode="inprocess")
    assert [r.error for r in rows] == [None] * 5
    assert rows[2].pnl_gbp == pytest.approx(pnl)


def test_other_run_ids_do_not_touch_live(synthetic_month, model):
    conn = synthetic_month
    run_decision(conn, NOW, model, GreedyOptimiser(), run_id="backtest-x")
    assert fetch(conn, "decisions", NOW, "live") == []
    assert len(fetch(conn, "decisions", NOW, "backtest-x")) == 48


def test_naive_now_rejected(synthetic_month, model):
    with pytest.raises(ValueError, match="timezone-aware"):
        run_decision(synthetic_month, NOW.replace(tzinfo=None), model, GreedyOptimiser())


def test_dashboard_calibration_reads_settled_live_forecasts(synthetic_month, model):
    from tempo.dashboard.data import DbSource

    conn = synthetic_month
    run_decision(conn, NOW, model, GreedyOptimiser())  # all 48 targets have prices in the synthetic month
    src = DbSource(conn)
    cal = src.calibration()
    assert "calibration" not in src.notes
    assert cal.nominal.tolist() == [0.1, 0.5, 0.9]
    assert ((cal.observed >= 0) & (cal.observed <= 1)).all()
    assert cal.attrs["n"] == 48 and 0 <= cal.attrs["coverage_p10_p90"] <= 1
