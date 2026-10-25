"""The Streamlit app (Report frame) runs without exceptions on synthetic data and every section renders."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tempo.dashboard import data

APP = str(Path(__file__).resolve().parents[2] / "tempo/dashboard/app.py")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("TEMPO_DATABASE_URL", "")
    monkeypatch.setenv("VULTR_API_KEY", "")
    monkeypatch.setenv("TEMPO_WORKER_URLS", "")
    from tempo.config import settings

    settings.cache_clear()
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def subheaders(at):
    return [h.value for h in at.subheader]


def test_app_runs_without_exceptions(app):
    assert not app.exception, [e.value for e in app.exception]
    assert app.title[0].value == "Tempo"
    heads = subheaders(app)
    assert any("period" in h and "of 48" in h for h in heads)  # Live sentence
    assert any(h.startswith("The windy week of") and "played forward" in h for h in heads)  # Replay sentence
    assert any("Click a decision" in h for h in heads)  # Audit sentence before a run
    assert any("% of perfect-foresight profit" in h for h in heads)  # Honesty sentence
    assert any("Most projects stop at a prediction" in h for h in heads)  # About
    assert any("settlement period" in c.value for c in app.caption)  # header strip


def test_live_section_has_pills_and_charts(app):
    assert any("Current period" in m.label for m in app.metric)
    assert len(app.get("vega_lite_chart")) >= 5  # price, strip, replay x3, ladder, calibration, regime


def test_audit_button_renders_five_columns_and_sentence(app):
    app.button(key="audit_run").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert sum(m.label == "PnL" for m in app.metric) == 5
    assert any("would have" in h or "made no difference" in h for h in subheaders(app))


def test_in_process_mode_runs_synchronously(app):
    app.radio(key="audit_mode").set_value("in-process").run()
    app.button(key="audit_run").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("mode: in-process" in c.value for c in app.caption)


def test_fork_mode_on_synthetic_renders_result_and_log(app):
    assert app.radio(key="audit_mode").value == "Tiger fork + Vultr workers"
    app.button(key="audit_run").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert sum(m.label == "PnL" for m in app.metric) == 5
    assert any("no fork was taken" in w.value for w in app.warning)
    assert any("mode: fork" in c.value for c in app.caption)


def test_running_fork_audit_shows_progress_and_disables_button(monkeypatch):
    import threading

    from tempo.dashboard.jobs import AuditJob

    gate = threading.Event()

    class Slow(data.SyntheticSource):
        def start_fork_audit(self, decision_id):
            def runner(conn, decision_id, *, mode, progress, **kw):
                progress.emit(-2, "forking", "fork audit-1-all requested")
                progress.emit(0, "replaying", "audit-1-0 dispatched to tempo-worker-3 (ewr)")
                gate.wait(timeout=10)
                return []

            return AuditJob(decision_id, conn_factory=lambda: None, runner=runner)

    monkeypatch.setattr(data, "pick_source", lambda url, now=None: (Slow(), "synthetic"))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.button(key="audit_run").click().run()
    at.run()  # the job started during the click; the next render shows it running
    try:
        assert not at.exception, [e.value for e in at.exception]
        assert at.button(key="audit_run").disabled
        assert any("Audit running" in i.value for i in at.info)
        texts = " ".join(m.value for m in at.markdown)
        assert "forking" in texts and "replaying" in texts
        assert any("dispatched to tempo-worker-3" in c.value for c in at.code)
    finally:
        gate.set()


def test_settlement_period_math():
    midnight, p = data.current_settlement_period(datetime(2026, 10, 23, 23, 10, tzinfo=UTC))
    assert p == 1 and midnight.day == 24
    _, p = data.current_settlement_period(datetime(2026, 10, 24, 22, 50, tzinfo=UTC))
    assert p == 48
    _, p_before = data.current_settlement_period(datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
    _, p_after = data.current_settlement_period(datetime(2026, 10, 25, 1, 30, tzinfo=UTC))
    assert (p_before, p_after) == (4, 6)
    _, last = data.current_settlement_period(datetime(2026, 10, 25, 23, 45, tzinfo=UTC))
    assert last == 50


def test_synthetic_audit_rows_contract():
    rows = data.SyntheticSource(datetime(2026, 1, 5, tzinfo=UTC)).audit_rows(42, failed_shift=2)
    assert sorted(rows["shift"]) == [-2, -1, 0, 1, 2]
    assert rows.loc[rows["shift"] == 0, "pnl_delta_gbp"].iloc[0] == 0.0
    assert rows.loc[rows["shift"] == 2, "pnl_gbp"].isna().all()
