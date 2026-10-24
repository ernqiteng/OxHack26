"""MID rules (docs/girik.md Phase 1): zero-volume dropped, N2EX kept but tagged, derived available_at."""

import pandas as pd
import pytest

from tempo.ingest.elexon import normalise


def mid(start: str, provider: str, price: float, volume: float, period: int = 1) -> dict:
    return {
        "dataset": "MID",
        "startTime": start,
        "dataProvider": provider,
        "settlementDate": start[:10],
        "settlementPeriod": period,
        "price": price,
        "volume": volume,
    }


ROWS = [
    mid("2026-01-05T00:00:00Z", "APXMIDP", 50.0, 120.0, 1),
    mid("2026-01-05T00:00:00Z", "N2EXMIDP", 0.0, 0.0, 1),  # dropped
    mid("2026-01-05T00:30:00Z", "APXMIDP", 0.0, 0.0, 2),  # APX zero-volume also dropped (real: 11/yr)
    mid("2026-01-05T00:30:00Z", "N2EXMIDP", 45.0, 8.0, 2),  # kept, tagged N2EXMIDP
]


def test_zero_volume_rows_dropped():
    df = normalise("MID", ROWS, mid_delay=10)
    assert len(df) == 4  # 2 surviving raw rows x (price + volume)
    assert (df["value"][df["series"].str.endswith(":volume")] > 0).all()
    assert not ((df["series"] == "APXMIDP") & (df["start_time"] == pd.Timestamp("2026-01-05T00:30Z"))).any()


def test_n2ex_retained_and_tagged():
    df = normalise("MID", ROWS, mid_delay=10)
    assert set(df["series"]) == {"APXMIDP", "APXMIDP:volume", "N2EXMIDP", "N2EXMIDP:volume"}
    n2ex = df[df["series"] == "N2EXMIDP"]
    assert len(n2ex) == 1 and n2ex.iloc[0]["value"] == 45.0


def test_volume_is_a_second_row_with_same_key_times():
    df = normalise("MID", ROWS, mid_delay=10)
    price = df[df["series"] == "APXMIDP"].iloc[0]
    vol = df[df["series"] == "APXMIDP:volume"].iloc[0]
    assert price["start_time"] == vol["start_time"] == pd.Timestamp("2026-01-05T00:00Z")
    assert price["available_at"] == vol["available_at"]
    assert (price["value"], vol["value"]) == (50.0, 120.0)


@pytest.mark.parametrize("delay", [0, 10, 25])
def test_available_at_is_start_plus_30_plus_delay(delay):
    df = normalise("MID", ROWS, mid_delay=delay)
    assert (df["available_at"] - df["start_time"] == pd.Timedelta(minutes=30 + delay)).all()


def test_delay_defaults_to_env(monkeypatch):
    monkeypatch.setenv("MID_AVAILABILITY_DELAY_MIN", "7")
    df = normalise("MID", ROWS)
    assert (df["available_at"] - df["start_time"] == pd.Timedelta(minutes=37)).all()
