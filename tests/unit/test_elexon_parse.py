"""normalise() on one real saved response per dataset (tests/fixtures/elexon_samples). No network."""

import json
from pathlib import Path

import pandas as pd
import pytest

from tempo.ingest.elexon import FORECAST_DATASETS, GRID_RAW_COLUMNS, _rows, normalise

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "elexon_samples"

# Known answers, counted once by hand from the saved files (raw rows -> grid_raw rows).
EXPECTED = {
    "MID_2025-10-26.json": 100,  # 96 raw: 46 N2EX zero-volume dropped, 50 APX -> price + volume rows
    "MID_2026-03-29.json": 94,  # 94 raw: 47 N2EX zero-volume dropped, 47 APX -> 94
    "WINDFOR_2025-10-26.json": 592,
    "NDF_2025-10-26.json": 618,
    "INDO_2025-10-26.json": 50,
    "FUELHH_2025-10-26.json": 980,
    "DISEBSP_2025-10-26.json": 50,
}


def load(name: str):
    return _rows(json.loads((SAMPLES / name).read_text(encoding="utf-8")))


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_normalise_sample(name, expected):
    dataset = name.split("_")[0]
    df = normalise(dataset, load(name), mid_delay=10)

    assert list(df.columns) == GRID_RAW_COLUMNS
    assert len(df) == expected
    assert (df["dataset"] == dataset).all()
    assert not df[["start_time", "available_at", "series", "value"]].isna().any().any()

    for col in ("start_time", "available_at"):
        assert isinstance(df[col].dtype, pd.DatetimeTZDtype), col
        assert str(df[col].dt.tz) == "UTC", col
    assert df["value"].dtype == float

    if dataset in FORECAST_DATASETS:
        # forecasts are published before the period they describe
        assert (df["available_at"] < df["start_time"]).any()
    else:
        assert (df["available_at"] >= df["start_time"]).all()

    # no duplicate primary keys
    assert not df.duplicated(subset=["start_time", "available_at", "dataset", "series"]).any()


def test_series_tags():
    assert set(normalise("FUELHH", load("FUELHH_2025-10-26.json"))["series"]) >= {"WIND", "CCGT", "NUCLEAR"}
    assert set(normalise("NDF", load("NDF_2025-10-26.json"))["series"]) == {"N"}
    assert set(normalise("WINDFOR", load("WINDFOR_2025-10-26.json"))["series"]) == {""}
    assert set(normalise("DISEBSP", load("DISEBSP_2025-10-26.json"))["series"]) == {""}


def test_windfor_is_hourly_and_stays_hourly():
    df = normalise("WINDFOR", load("WINDFOR_2025-10-26.json"))
    assert (df["start_time"].dt.minute == 0).all()
    assert df["settlement_period"].isna().all()


def test_disebsp_uses_created_time_and_sell_price():
    raw = load("DISEBSP_2025-10-26.json")
    df = normalise("DISEBSP", raw)
    first = raw[0]
    row = df[df["start_time"] == pd.Timestamp(first["startTime"])].iloc[0]
    assert row["value"] == first["systemSellPrice"]
    assert row["available_at"] == pd.Timestamp(first["createdDateTime"])
    # system price is published about a day after the period: a 24 h lag is the known shape
    assert (df["available_at"] - df["start_time"]).min() > pd.Timedelta(hours=12)


def test_empty_and_unknown():
    assert normalise("MID", []).empty
    assert list(normalise("MID", []).columns) == GRID_RAW_COLUMNS
    with pytest.raises(ValueError, match="unknown dataset"):
        normalise("NOPE", [{"a": 1}])


def test_naive_timestamp_is_refused():
    rows = load("WINDFOR_2025-10-26.json")[:3]
    for r in rows:
        r["publishTime"] = r["publishTime"].rstrip("Z")  # no tz marker
    with pytest.raises(ValueError, match="timezone-aware"):
        normalise("WINDFOR", rows)
