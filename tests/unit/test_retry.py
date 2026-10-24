"""ElexonClient retry/backoff with respx: 429 then 200 -> one success, one sleep; five 500s -> raise."""

import httpx
import pytest
import respx

BASE = "https://elexon.test/api/v1"


def make_client(sleeps: list[float]):
    from tempo.ingest.elexon import ElexonClient

    return ElexonClient(base=BASE, http=httpx.Client(), max_attempts=5, backoff_s=1.0, sleep=sleeps.append)


@respx.mock
def test_429_then_200_is_one_success_and_one_sleep():
    sleeps: list[float] = []
    # MID's live (non-stream) endpoint is /balancing/pricing/market-index, not /datasets/MID (needs.md B3)
    route = respx.get(f"{BASE}/balancing/pricing/market-index").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"data": [{"x": 1}]}),
        ]
    )
    client = make_client(sleeps)
    rows = client.fetch("MID", **{"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"})
    assert rows == [{"x": 1}]
    assert route.call_count == 2
    assert sleeps == [2.0]  # Retry-After honoured over the 1 s backoff
    assert client.requests_made == 2


@respx.mock
def test_five_500s_raise_after_four_sleeps():
    sleeps: list[float] = []
    route = respx.get(f"{BASE}/datasets/MID/stream").mock(return_value=httpx.Response(500))
    client = make_client(sleeps)
    with pytest.raises(RuntimeError, match="after 5 attempts"):
        client.fetch_stream("MID", **{"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"})
    assert route.call_count == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]  # exponential, no sleep after the final attempt


@respx.mock
def test_404_is_not_retried():
    sleeps: list[float] = []
    route = respx.get(f"{BASE}/balancing/pricing/market-index").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        make_client(sleeps).fetch("MID")
    assert route.call_count == 1 and sleeps == []


@respx.mock
def test_stream_returns_bare_list_and_per_day_path():
    respx.get(f"{BASE}/datasets/NDF/stream").mock(return_value=httpx.Response(200, json=[{"a": 1}, {"a": 2}]))
    respx.get(f"{BASE}/balancing/settlement/system-prices/2026-01-05").mock(
        return_value=httpx.Response(200, json={"data": [{"p": 1}]})
    )
    client = make_client([])
    assert client.fetch_stream("NDF", publishDateTimeFrom="x", publishDateTimeTo="y") == [{"a": 1}, {"a": 2}]
    assert client.fetch("DISEBSP", date="2026-01-05") == [{"p": 1}]
