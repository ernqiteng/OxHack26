"""make_synthetic_market: determinism, row counts, built-in patterns, grid_raw format."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tests.fixtures.synthetic import COLUMNS, make_synthetic_market


@pytest.fixture(scope="module")
def market():
    return make_synthetic_market()


@pytest.fixture(scope="module")
def mid(market):
    m = market[market.dataset == "MID"].copy()
    local = m.start_time.dt.tz_convert("Europe/London")
    m["hhmm"] = local.dt.strftime("%H:%M")
    m["iso_week"] = local.dt.isocalendar().week.astype(int)
    m["hour"] = local.dt.hour
    return m


# --- the four tests from docs/ernqi.md Phase 0 -------------------------------


def test_same_seed_is_identical():
    pd.testing.assert_frame_equal(make_synthetic_market(seed=3), make_synthetic_market(seed=3))


def test_different_seed_differs():
    assert not make_synthetic_market(seed=1).value.equals(make_synthetic_market(seed=2).value)


def test_60_days_give_60x48_mid_rows(mid):
    assert len(mid) == 60 * 48


def test_night_cheaper_than_evening_peak(mid):
    assert mid[mid.hhmm == "03:00"].value.mean() < mid[mid.hhmm == "18:00"].value.mean()


def test_windy_even_weeks_have_cheaper_nights(mid):
    night = mid[(mid.hour >= 1) & (mid.hour < 5)]
    even = night[night.iso_week % 2 == 0].value.mean()
    odd = night[night.iso_week % 2 == 1].value.mean()
    assert even < odd - 20  # built-in drop is 30


# --- format checks, so Girik's and Ayo's code can trust the rows -------------


def test_grid_raw_columns_and_utc(market):
    assert list(market.columns) == COLUMNS
    assert str(market.start_time.dt.tz) == "UTC"
    assert str(market.available_at.dt.tz) == "UTC"
    assert market.value.notna().all()


def test_primary_key_unique(market):
    assert not market.duplicated(["start_time", "available_at", "dataset", "series"]).any()


def test_dataset_cadence_and_series(market):
    counts = market.groupby(["dataset", "series"]).size().to_dict()
    assert counts == {("MID", "APXMIDP"): 60 * 48, ("NDF", "N"): 60 * 48, ("WINDFOR", ""): 60 * 24}


def test_available_at_rules(market):
    lag = market.available_at - market.start_time
    assert (lag[market.dataset == "MID"] == timedelta(minutes=40)).all()
    assert (lag[market.dataset == "WINDFOR"] == timedelta(minutes=-30)).all()
    assert (lag[market.dataset == "NDF"] == timedelta(minutes=-30)).all()


def test_wind_high_on_windy_weeks(market):
    w = market[market.dataset == "WINDFOR"]
    week = w.start_time.dt.tz_convert("Europe/London").dt.isocalendar().week.astype(int)
    assert w[week % 2 == 0].value.mean() > w[week % 2 == 1].value.mean() + 5_000


def test_settlement_period_1_to_48_in_winter(market):
    sp = market[market.dataset == "MID"].settlement_period
    assert sp.min() == 1 and sp.max() == 48


def test_clock_change_day_has_50_periods():
    """Starting on the 25 Oct 2026 clock change: that UK day has 50 periods and they keep counting."""
    m = make_synthetic_market(days=3, start=datetime(2026, 10, 24, 23, tzinfo=UTC))  # 00:00 BST
    day = m[(m.dataset == "MID") & (m.settlement_date == pd.Timestamp("2026-10-25").date())]
    assert sorted(day.settlement_period) == list(range(1, 51))
