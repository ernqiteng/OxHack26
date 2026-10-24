"""Clock-change days: 2025-10-26 (clocks back, 50 periods) and 2026-03-29 (clocks forward, 46 periods).

start_time must come from the API's UTC startTime, never from settlementDate + settlementPeriod.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from tempo.ingest.elexon import _rows, normalise

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "elexon_samples"


def apx_prices(name: str, settlement_date: date) -> pd.DataFrame:
    df = normalise("MID", _rows(json.loads((SAMPLES / name).read_text(encoding="utf-8"))))
    df = df[(df["series"] == "APXMIDP") & (df["settlement_date"] == settlement_date)]
    return df.sort_values("settlement_period").reset_index(drop=True)


def test_autumn_day_has_50_distinct_start_times():
    df = apx_prices("MID_2025-10-26.json", date(2025, 10, 26))
    assert len(df) == 50
    assert df["start_time"].nunique() == 50
    assert list(df["settlement_period"]) == list(range(1, 51))
    assert df["start_time"].iloc[0] == pd.Timestamp("2025-10-25T23:00Z")  # period 1 = 00:00 BST
    assert df["start_time"].iloc[-1] == pd.Timestamp("2025-10-26T23:30Z")  # period 50 = 23:30 GMT
    assert (df["start_time"].diff().dropna() == pd.Timedelta(minutes=30)).all()


def test_autumn_repeated_local_hour_does_not_collide():
    """01:00 happens twice (BST then GMT). Periods 3 and 5 are both '01:00 local' but 1 h apart in UTC."""
    df = apx_prices("MID_2025-10-26.json", date(2025, 10, 26)).set_index("settlement_period")
    assert df.loc[3, "start_time"] == pd.Timestamp("2025-10-26T00:00Z")
    assert df.loc[5, "start_time"] == pd.Timestamp("2025-10-26T01:00Z")
    local = df["start_time"].dt.tz_convert("Europe/London")
    assert local.loc[3].strftime("%H:%M") == local.loc[5].strftime("%H:%M") == "01:00"


def test_spring_day_has_46_distinct_start_times():
    df = apx_prices("MID_2026-03-29.json", date(2026, 3, 29))
    assert len(df) == 46
    assert df["start_time"].nunique() == 46
    assert list(df["settlement_period"]) == list(range(1, 47))
    assert df["start_time"].iloc[0] == pd.Timestamp("2026-03-29T00:00Z")  # 00:00 GMT
    assert df["start_time"].iloc[-1] == pd.Timestamp("2026-03-29T22:30Z")  # 23:30 BST
    assert (df["start_time"].diff().dropna() == pd.Timedelta(minutes=30)).all()


def test_naive_derivation_would_be_wrong():
    """Document why we never derive start_time: period n at 00:00 + 30min*(n-1) UTC is off by an hour
    for every period after the change on 2025-10-26."""
    df = apx_prices("MID_2025-10-26.json", date(2025, 10, 26))
    naive = pd.Timestamp("2025-10-26T00:00Z") + pd.to_timedelta(
        (df["settlement_period"] - 1) * 30, unit="min"
    )
    assert (
        naive != df["start_time"]
    ).sum() == 50  # every row differs (periods 1-4 by -1h, 5-50 by +1h... all wrong)
