"""DbSource degrades per method when tables are missing, and the app still renders with it."""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tempo.dashboard import data


class BrokenConn:
    """Every query fails the way a missing relation does."""

    def execute(self, sql, params=()):
        raise RuntimeError('relation "prices_hh" does not exist')


def test_every_method_falls_back_with_a_note():
    src = data.DbSource(BrokenConn())
    assert not src.recent_prices().empty
    assert not src.next_forecast().empty
    assert src.todays_schedule().empty  # empty is honest here: no live decisions yet
    assert src.latest_hold() is None
    assert not src.recent_decisions().empty
    assert not src.backtest_summary().empty
    for method in ("recent_prices", "next_forecast", "recent_decisions", "backtest_summary"):
        assert "Showing synthetic data" in src.notes[method], method
    assert "prices_hh" in src.notes["recent_prices"]


def test_audit_on_synthetic_decisions_never_touches_db():
    src = data.DbSource(BrokenConn())
    did = int(src.recent_decisions().decision_id.iloc[0])
    rows = src.run_audit(did)
    assert sorted(rows["shift"]) == [-2, -1, 0, 1, 2]


def test_app_renders_with_broken_db_and_shows_notes(monkeypatch):
    monkeypatch.setattr(data, "pick_source", lambda url, now=None: (data.DbSource(BrokenConn()), "connected"))
    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "tempo/dashboard/app.py"), default_timeout=60
    )
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("recent_prices" in w.value for w in at.tabs[0].warning)
    at.button(key="audit_run").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs[2].metric) >= 5


def test_failed_shift_renders_as_failed(monkeypatch):
    class FailingShift(data.SyntheticSource):
        def run_audit(self, decision_id):
            rows = self.audit_rows(decision_id, failed_shift=2)
            rows["error"] = [None, None, None, None, "TigerTimeout: fork still QUEUED"]
            return rows

    monkeypatch.setattr(data, "pick_source", lambda url, now=None: (FailingShift(), "synthetic"))
    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "tempo/dashboard/app.py"), default_timeout=60
    )
    at.run()
    at.button(key="audit_run").click().run()
    assert not at.exception, [e.value for e in at.exception]
    audit = at.tabs[2]
    assert any(m.value == "failed" for m in audit.metric)
    assert any("shift +2 failed" in e.value for e in audit.error)
    assert any("one period later" in s.value for s in audit.success)


@pytest.mark.parametrize("value", [pd.DataFrame(), None])
def test_try_treats_empty_as_missing(value):
    src = data.DbSource(BrokenConn())
    out = src._try("x", lambda: value, lambda: "fallback")
    assert out == "fallback" and "no rows yet" in src.notes["x"]


def test_self_grade_converts_ernqi_fraction_to_percent(monkeypatch):
    import tempo.audit.selfgrade as sg

    monkeypatch.setattr(
        sg,
        "self_grade",
        lambda conn, since: {
            "pct_within_one_period": 0.71,
            "n_cycles": 38,
            "mean_cost_of_mistiming_gbp": 9.4,
        },
    )
    src = data.DbSource(BrokenConn())
    out = src.self_grade()
    assert out == {"pct_within_one_period": 71.0, "n_cycles": 38, "mean_cost_of_mistiming_gbp": 9.4}
    assert "self_grade" not in src.notes


def test_self_grade_with_no_cycles_falls_back_with_note(monkeypatch):
    import tempo.audit.selfgrade as sg

    monkeypatch.setattr(
        sg,
        "self_grade",
        lambda conn, since: {
            "pct_within_one_period": None,
            "n_cycles": 0,
            "mean_cost_of_mistiming_gbp": None,
        },
    )
    src = data.DbSource(BrokenConn())
    out = src.self_grade()
    assert out["pct_within_one_period"] == 71.0  # synthetic stand-in
    assert "no completed live cycles" in src.notes["self_grade"]


def test_weak_points_fall_back_without_backtest_rows():
    src = data.DbSource(BrokenConn())
    assert len(src.weak_points()) >= 3 and "weak_points" in src.notes
