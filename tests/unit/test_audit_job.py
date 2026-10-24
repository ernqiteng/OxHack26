"""Background audit job used by the dashboard's fork mode, with an injected runner. No network, no DB."""

import threading
import time
from datetime import UTC, datetime

from tempo.audit.orchestrator import SHIFTS, AuditRow
from tempo.dashboard.jobs import AuditJob, CompletedJob


class Conn:
    closed = False

    def close(self):
        self.closed = True


def rows_for(decision_id):
    t = datetime(2026, 1, 1, tzinfo=UTC)
    return [AuditRow(decision_id, s, 100.0 + s, float(s), "fork", t, t, "svc", f"w{s}") for s in SHIFTS]


def test_job_runs_in_background_and_reports_progress():
    gate = threading.Event()
    seen = {}

    def runner(conn, decision_id, *, mode, progress, **kw):
        seen["mode"], seen["kw"] = mode, kw
        progress.emit(0, "forking", "fork requested")
        gate.wait(timeout=5)
        progress.emit(0, "done", "£100.00")
        return rows_for(decision_id)

    conn = Conn()
    job = AuditJob(7, conn_factory=lambda: conn, runner=runner, shift_timeout=30)
    time.sleep(0.1)
    assert not job.done and job.states()[0] == "forking" and job.running_s > 0
    assert any("fork requested" in line for line in job.log_lines())
    gate.set()
    assert job._done.wait(5)
    assert job.done and job.error is None and conn.closed
    assert seen == {"mode": "fork", "kw": {"shift_timeout": 30}}
    assert list(job.rows["shift"]) == list(SHIFTS) and job.rows["worker_id"].tolist()[0] == "w-2"
    assert job.elapsed_s is not None and job.states()[0] == "done"


def test_job_surfaces_a_crash_instead_of_hanging():
    def runner(conn, decision_id, *, mode, progress, **kw):
        raise RuntimeError("Tiger down")

    job = AuditJob(7, conn_factory=Conn, runner=runner)
    assert job._done.wait(5)
    assert job.done and job.rows is None and "RuntimeError: Tiger down" in job.error
    assert any("audit crashed" in line for line in job.log_lines())


def test_job_survives_connection_failure():
    def boom():
        raise ConnectionError("no route")

    job = AuditJob(7, conn_factory=boom, runner=lambda *a, **k: rows_for(7))
    assert job._done.wait(5)
    assert "ConnectionError" in job.error


def test_completed_job_shape():
    import pandas as pd

    job = CompletedJob(1, pd.DataFrame({"shift": list(SHIFTS)}), note="synthetic")
    assert job.done and job.states() == {s: "done" for s in SHIFTS} and job.log_lines() == []


def frame(deltas):
    import pandas as pd

    return pd.DataFrame({"shift": list(deltas), "pnl_delta_gbp": list(deltas.values())})


def test_hero_sentence_names_worst_shift_when_tempo_was_best():
    from tempo.dashboard.jobs import hero_sentence

    s = hero_sentence(frame({-2: -52.95, -1: -20.0, 0: 0.0, 1: -14.3, 2: -30.7}), "charge")
    assert s == "Charging an hour earlier would have cost £52.95. Tempo picked the best of the five."


def test_hero_sentence_admits_a_better_shift():
    from tempo.dashboard.jobs import hero_sentence

    s = hero_sentence(frame({-2: -5.0, -1: 5.2, 0: 0.0, 1: -1.0, 2: -9.0}), "discharge")
    assert s == "Selling 30 minutes earlier would have earned £5.20 more. Tempo mistimed this one."


def test_hero_sentence_handles_no_difference_and_missing():
    from tempo.dashboard.jobs import hero_sentence

    assert hero_sentence(frame({-2: 0.0, -1: 0.0, 0: 0.0, 1: 0.0, 2: 0.0}), "charge").startswith("Shifting")
    assert hero_sentence(frame({-2: None, -1: None, 0: None, 1: None, 2: None}), "charge") is None
