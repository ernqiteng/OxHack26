"""The dashboard headlines one strategy everywhere: tempo (LightGBM + greedy), which the live decider runs.

Known answer: the latest Tiger run db-20261024T202144Z, 100 unseen weeks, pooled pnl / perfect pnl:
simple rule 33.1%, persistence 52.9%, tempo 66.4%, tempo_lp 68.3%. The page once took the LAST
tempo-prefixed row (tempo_lp, shown by its raw id) while the "where it's weak" lines described tempo.

The page tests drive the real app.py through Streamlit's AppTest with a source that serves the real run's
numbers through DbSource.backtest_summary (the dashboard's own labelling and ordering), and assert on what is
rendered: header, honesty sentence, weak statements and the calibration caption.
"""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tempo.backtest import metrics
from tempo.backtest.metrics import _main_strategy, weak_statements
from tempo.dashboard import data, ui
from tempo.dashboard.data import DbSource, calibration_sentence

APP = str(Path(__file__).resolve().parents[2] / "tempo/dashboard/app.py")
PERFECT = 88388.0
PNL = {"simple_rule": 29265.0, "persistence_greedy": 46798.0, "tempo": 58711.0, "tempo_lp": 60391.0}
TEMPO = "Tempo (LightGBM forecast + same optimiser)"


def latest_run_summary() -> pd.DataFrame:
    """What DbSource.backtest_summary() returns for the latest run, with the one query stubbed."""
    raw = pd.DataFrame({"strategy": ["perfect", "tempo_lp", "simple_rule", "tempo", "persistence_greedy"]})
    raw["pnl_gbp"] = raw.strategy.map({**PNL, "perfect": PERFECT})
    raw["pct_of_perfect"] = 100 * raw.pnl_gbp / PERFECT
    src = DbSource(conn=None)
    src._df = lambda sql, params=(): raw.copy()  # noqa: SLF001
    return src.backtest_summary()


def latest_run_rows() -> pd.DataFrame:
    """backtest_results-shaped rows with the same pooled totals, split over 4 weeks (2 calm, 2 windy)."""
    weeks = pd.date_range("2025-01-06", periods=4, freq="7D").date
    rows = []
    for i, week in enumerate(weeks):
        for strategy, pnl in {**PNL, "perfect": PERFECT}.items():
            rows.append(
                {"run_id": "r", "week_start": week, "strategy": strategy, "pnl_gbp": pnl / 4,
                 "perfect_pnl_gbp": PERFECT / 4, "pct_of_perfect": 100 * pnl / PERFECT,
                 "regime": "windy" if i % 2 else "calm"}
            )  # fmt: skip
    return pd.DataFrame(rows)


class RealRun(data.SyntheticSource):
    """Synthetic everywhere except the honesty numbers, which are the real run's."""

    def backtest_summary(self):
        return latest_run_summary()

    def backtest_weeks(self):
        return 100

    def weak_points(self):
        return weak_statements(latest_run_rows())

    def calibration(self):
        cal = super().calibration()
        cal.attrs.update(n=390, coverage_p10_p90=0.7718)
        return cal


@pytest.fixture(scope="module")
def page():
    mp = pytest.MonkeyPatch()
    mp.setenv("TEMPO_DATABASE_URL", "")
    mp.setenv("VULTR_API_KEY", "")
    mp.setenv("TEMPO_WORKER_URLS", "")
    source = RealRun(datetime(2026, 1, 5, tzinfo=UTC))
    mp.setattr(data, "pick_source", lambda url, now=None: (source, "synthetic"))
    from tempo.config import settings

    settings.cache_clear()
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    yield at
    mp.undo()


def rendered_text(at) -> str:
    parts = [m.value for m in at.markdown] + [h.value for h in at.subheader] + [c.value for c in at.caption]
    return "\n".join(parts)


# --- the rendered page -------------------------------------------------------------------------------------


def test_page_renders(page):
    assert not page.exception, [e.value for e in page.exception]


def test_header_names_tempo_66_4(page):
    header = "Tempo captures 66.4% of perfect foresight over 100 unseen weeks"
    assert any(header in m.value for m in page.markdown)


def test_honesty_sentence_names_tempo_66_4(page):
    heads = [h.value for h in page.subheader]
    assert "Tempo captures 66.4% of perfect-foresight profit over 100 unseen weeks." in heads


def test_the_lp_variant_is_never_the_headline_or_a_raw_id(page):
    text = rendered_text(page)
    assert "tempo_lp" not in text
    assert "Tempo LP captures" not in text
    assert "68.3% of perfect" not in text


def test_weak_statements_on_the_page_describe_tempo(page):
    text = rendered_text(page)
    assert "of Tempo's profit" in text
    assert "Tempo (LP)" not in text


def test_calibration_caption_states_the_verdict(page):
    verdict = "held 77% of actual prices against an 80% target: slightly overconfident"
    assert any(verdict in c.value for c in page.caption)


# --- the pieces the page is built from -------------------------------------------------------------------


def test_summary_labels_and_orders_all_five():
    s = latest_run_summary()
    assert s.strategy.tolist() == [
        "Simple rule (charge 01:00-05:00, sell 17:00-19:00)",
        "Persistence forecast + same optimiser",
        TEMPO,
        "Tempo LP (LightGBM forecast + LP optimiser)",
        "Perfect knowledge of the future",
    ]
    assert s.pct_of_perfect.tolist() == [33.1, 52.9, 66.4, 68.3, 100.0]


def test_ladder_highlights_only_tempo():
    bars = ui.ladder(latest_run_summary(), main_prefix=TEMPO).data  # Altair lifts shared data to the layer
    assert bars.loc[bars.is_main, "strategy"].tolist() == [TEMPO]


def test_one_headline_strategy_for_page_and_weak_statements():
    assert data.HEADLINE_STRATEGY == metrics.HEADLINE_STRATEGY == "tempo"
    assert _main_strategy({"tempo_lp", "tempo", "persistence_greedy"}) == "tempo"


def test_calibration_sentence_states_a_verdict():
    """Known answer from Tiger: 390 settled live forecasts, 77% inside the p10-p90 band, 80% target."""
    live = calibration_sentence(390, 0.7718)
    assert live.startswith(
        "390 settled live forecasts: the p10–p90 band held 77% of actual prices against an 80%"
    )
    assert "slightly overconfident (the band is too narrow)" in live
    assert "p50 forecast only" in live
    holdout = calibration_sentence(1344, 0.63)  # the training holdout
    assert "overconfident (the band is too narrow)" in holdout and "slightly" not in holdout
    assert "about right" in calibration_sentence(500, 0.80)
    assert "about right" in calibration_sentence(500, 0.815)
    assert "under-confident (the band is too wide)" in calibration_sentence(500, 0.86)
