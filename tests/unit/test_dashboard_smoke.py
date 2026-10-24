"""The Streamlit app runs without exceptions on synthetic data and every tab shows something."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tempo.dashboard import data


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("TEMPO_DATABASE_URL", raising=False)
    monkeypatch.setenv("TEMPO_DATABASE_URL", "")
    from tempo.config import settings

    settings.cache_clear()
    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "tempo/dashboard/app.py"), default_timeout=60
    )
    at.run()
    return at


def test_app_runs_without_exceptions(app):
    assert not app.exception, [e.value for e in app.exception]
    assert app.title[0].value == "Tempo"
    assert [t.label for t in app.tabs] == ["Live", "Replay", "Timing audit", "Honesty", "About"]
    assert "synthetic" in app.caption[0].value


def test_live_tab_has_period_and_charts(app):
    live = app.tabs[0]
    assert any("settlement period" in m.label.lower() for m in live.metric)
    assert len(live.get("vega_lite_chart")) >= 2


def test_replay_and_honesty_tabs_render_tables_and_charts(app):
    replay, honesty = app.tabs[1], app.tabs[3]
    assert len(replay.get("vega_lite_chart")) >= 3
    assert len(honesty.dataframe) >= 1
    assert len(honesty.get("vega_lite_chart")) >= 1


def test_audit_button_renders_five_columns(app):
    app.button(key="audit_run").click().run()
    assert not app.exception, [e.value for e in app.exception]
    audit = app.tabs[2]
    assert len(audit.metric) >= 5
    assert any("one period later" in s.value for s in audit.success)


def test_about_tab_has_text(app):
    assert any("Tempo" in m.value for m in app.tabs[4].markdown)


def test_settlement_period_math():
    # 00:10 London (BST, UTC+1) on 24 Oct 2026 -> period 1; 23:50 London -> period 48
    midnight, p = data.current_settlement_period(datetime(2026, 10, 23, 23, 10, tzinfo=UTC))
    assert p == 1 and midnight.day == 24
    _, p = data.current_settlement_period(datetime(2026, 10, 24, 22, 50, tzinfo=UTC))
    assert p == 48
    # clock-change day 25 Oct 2026: 01:30 BST and 01:30 GMT are different periods, day has 50
    _, p_before = data.current_settlement_period(datetime(2026, 10, 25, 0, 30, tzinfo=UTC))  # 01:30 BST
    _, p_after = data.current_settlement_period(datetime(2026, 10, 25, 1, 30, tzinfo=UTC))  # 01:30 GMT
    assert (p_before, p_after) == (4, 6)
    _, last = data.current_settlement_period(datetime(2026, 10, 25, 23, 45, tzinfo=UTC))
    assert last == 50


def test_synthetic_audit_rows_contract():
    rows = data.SyntheticSource(datetime(2026, 1, 5, tzinfo=UTC)).audit_rows(42, failed_shift=2)
    assert sorted(rows["shift"]) == [-2, -1, 0, 1, 2]
    assert rows.loc[rows["shift"] == 0, "pnl_delta_gbp"].iloc[0] == 0.0
    assert rows.loc[rows["shift"] == 2, "pnl_gbp"].isna().all()
