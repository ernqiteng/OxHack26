"""Poller (docs/girik.md Phase 2): unchanged lastUpdated -> no fetch; changed -> exactly one fetch for that
dataset; NDF fetched in <= 1-day windows; a failed fetch is retried next cycle. respx + freezegun, no DB."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from freezegun import freeze_time

from tempo.ingest.elexon import ElexonClient
from tempo.ingest.poll import Poller

BASE = "https://elexon.test/api/v1"
NOW = "2026-10-25T12:00:00Z"  # the autumn clock-change day: nothing special should be needed

MID_ROW = dict(
    dataset="MID", startTime="2026-10-25T10:00:00Z", dataProvider="APXMIDP", settlementDate="2026-10-25",
    settlementPeriod=23, price=80.0, volume=50.0,
)  # fmt: skip
WINDFOR_ROW = dict(
    dataset="WINDFOR", startTime="2026-10-25T14:00:00Z", publishTime="2026-10-25T11:30:00Z", generation=9000.0
)
NDF_ROW = dict(
    dataset="NDF", startTime="2026-10-25T14:00:00Z", publishTime="2026-10-25T11:30:00Z",
    settlementDate="2026-10-25", settlementPeriod=31, boundary="N", demand=30000.0,
)  # fmt: skip


def meta(**updated):
    return httpx.Response(200, json={"data": [{"dataset": k, "lastUpdated": v} for k, v in updated.items()]})


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as r:
        yield {
            "meta": r.get(f"{BASE}/datasets/metadata/latest"),
            "MID": r.get(f"{BASE}/balancing/pricing/market-index").mock(
                return_value=httpx.Response(200, json={"data": [MID_ROW]})
            ),
            "WINDFOR": r.get(f"{BASE}/datasets/WINDFOR").mock(
                return_value=httpx.Response(200, json={"data": [WINDFOR_ROW]})
            ),
            "NDF": r.get(f"{BASE}/datasets/NDF").mock(
                return_value=httpx.Response(200, json={"data": [NDF_ROW]})
            ),
        }


def make_poller(sunk):
    client = ElexonClient(base=BASE, http=httpx.Client(), sleep=lambda s: None)
    return Poller(client, sink=lambda df: sunk.append(df) or len(df), datasets=("MID", "WINDFOR", "NDF"))


@freeze_time(NOW)
def test_first_cycle_fetches_every_dataset(routes):
    routes["meta"].mock(return_value=meta(MID="t1", WINDFOR="t1", NDF="t1"))
    sunk = []
    assert make_poller(sunk).poll_once() == {"MID": 2, "WINDFOR": 1, "NDF": 1}  # MID = price + volume rows


@freeze_time(NOW)
def test_unchanged_last_updated_triggers_no_fetch(routes):
    routes["meta"].mock(return_value=meta(MID="t1", WINDFOR="t1", NDF="t1"))
    p = make_poller([])
    p.poll_once()
    calls = {k: routes[k].call_count for k in ("MID", "WINDFOR", "NDF")}
    assert p.poll_once() == {}
    assert {k: routes[k].call_count for k in ("MID", "WINDFOR", "NDF")} == calls  # no new data calls


@freeze_time(NOW)
def test_changed_last_updated_triggers_exactly_one_fetch_for_that_dataset(routes):
    routes["meta"].mock(
        side_effect=[meta(MID="t1", WINDFOR="t1", NDF="t1"), meta(MID="t2", WINDFOR="t1", NDF="t1")]
    )
    p = make_poller([])
    p.poll_once()
    before = {k: routes[k].call_count for k in ("MID", "WINDFOR", "NDF")}
    assert set(p.poll_once()) == {"MID"}
    assert routes["MID"].call_count == before["MID"] + 1
    assert routes["WINDFOR"].call_count == before["WINDFOR"]
    assert routes["NDF"].call_count == before["NDF"]


@freeze_time(NOW)
def test_ndf_is_fetched_in_one_day_windows(routes):
    """/datasets/NDF rejects publish windows over 1 day; a 2-day lookback must become two calls."""
    routes["meta"].mock(return_value=meta(NDF="t1"))
    p = make_poller([])
    p.datasets = ("NDF",)
    p.poll_once()
    windows = []
    for call in routes["NDF"].calls:
        q = call.request.url.params
        s = datetime.fromisoformat(q["publishDateTimeFrom"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(q["publishDateTimeTo"].replace("Z", "+00:00"))
        windows.append((s, e))
    assert len(windows) == 2
    assert all(e - s <= timedelta(days=1) for s, e in windows)
    assert windows[0][0] == datetime(2026, 10, 23, 12, tzinfo=UTC) and windows[-1][1] == datetime(
        2026, 10, 25, 12, tzinfo=UTC
    )


@freeze_time(NOW)
def test_mid_uses_the_market_index_endpoint_with_a_two_day_window(routes):
    routes["meta"].mock(return_value=meta(MID="t1"))
    p = make_poller([])
    p.datasets = ("MID",)
    p.poll_once()
    (call,) = routes["MID"].calls
    assert call.request.url.params["from"] == "2026-10-23T12:00:00Z"
    assert call.request.url.params["to"] == "2026-10-25T12:00:00Z"


@freeze_time(NOW)
def test_failed_fetch_is_retried_next_cycle_and_does_not_stop_others(routes):
    routes["meta"].mock(return_value=meta(MID="t1", WINDFOR="t1", NDF="t1"))
    routes["WINDFOR"].mock(
        side_effect=[httpx.Response(404), httpx.Response(200, json={"data": [WINDFOR_ROW]})]
    )
    p = make_poller([])
    first = p.poll_once()
    assert set(first) == {"MID", "NDF"}  # WINDFOR failed, the others still went in
    assert "WINDFOR" not in p.last_seen
    second = p.poll_once()  # same lastUpdated, but WINDFOR was never stored, so it is retried
    assert set(second) == {"WINDFOR"}


@freeze_time(NOW)
def test_run_survives_a_metadata_outage(routes):
    routes["meta"].mock(side_effect=[httpx.Response(404), meta(MID="t1", WINDFOR="t1", NDF="t1")])
    sleeps = []
    p = make_poller([])
    p.run(interval_s=60, iterations=2, sleep=sleeps.append)
    assert sleeps == [60]
    assert set(p.last_seen) == {"MID", "WINDFOR", "NDF"}


def test_dataset_missing_from_metadata_is_skipped(routes):
    routes["meta"].mock(return_value=meta(MID="t1"))
    p = make_poller([])
    with freeze_time(NOW):
        assert set(p.poll_once()) == {"MID"}
    assert routes["NDF"].call_count == 0
