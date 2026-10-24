"""TigerClient against a mocked Tiger REST API (respx). No network."""

import base64

import httpx
import pytest
import respx

from tempo.infra.tiger import Service, TigerClient, TigerError, TigerForkFailed, TigerTimeout

BASE = "https://tiger.test/public/api/v1"
PROJECT = "proj-123"
PRIMARY = "svc-primary"


class FakeTime:
    """Deterministic sleep/clock pair so wait_ready can be tested without waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


@pytest.fixture
def ft() -> FakeTime:
    return FakeTime()


@pytest.fixture
def tiger(ft: FakeTime) -> TigerClient:
    http = httpx.Client(base_url=BASE, auth=("key", "secret"))
    return TigerClient(PROJECT, "key", "secret", client=http, sleep=ft.sleep, clock=ft.clock)


def service_json(service_id: str, status: str, name: str = "audit-1-0", **extra) -> dict:
    body = {
        "service_id": service_id,
        "name": name,
        "status": status,
        "endpoint": {"host": f"{service_id}.tsdb.cloud", "port": 34567},
    }
    body.update(extra)
    return body


@respx.mock
def test_fork_posts_body_and_basic_auth(tiger: TigerClient):
    route = respx.post(f"{BASE}/projects/{PROJECT}/services/{PRIMARY}/forkService").mock(
        return_value=httpx.Response(202, json=service_json("svc-fork", "QUEUED", initial_password="pw1"))
    )

    svc = tiger.fork(PRIMARY, "audit-1-0")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"key:secret").decode()
    assert request.headers["Content-Type"].startswith("application/json")
    import json

    assert json.loads(request.content) == {
        "fork_strategy": "NOW",
        "name": "audit-1-0",
        "environment_tag": "DEV",
    }
    assert svc == Service.from_api(service_json("svc-fork", "QUEUED", initial_password="pw1"))
    assert svc.initial_password == "pw1"
    assert svc.host == "svc-fork.tsdb.cloud" and svc.port == 34567


@respx.mock
def test_fork_last_snapshot_strategy(tiger: TigerClient):
    route = respx.post(f"{BASE}/projects/{PROJECT}/services/{PRIMARY}/forkService").mock(
        return_value=httpx.Response(202, json=service_json("svc-fork", "QUEUED"))
    )
    tiger.fork(PRIMARY, "x", fork_strategy="LAST_SNAPSHOT")
    import json

    assert json.loads(route.calls.last.request.content)["fork_strategy"] == "LAST_SNAPSHOT"


@respx.mock
def test_fork_http_error_raises(tiger: TigerClient):
    respx.post(f"{BASE}/projects/{PROJECT}/services/{PRIMARY}/forkService").mock(
        return_value=httpx.Response(409, json={"message": "parent not READY"})
    )
    with pytest.raises(TigerError, match="409"):
        tiger.fork(PRIMARY, "x")


@respx.mock
def test_wait_ready_polls_until_ready(tiger: TigerClient, ft: FakeTime):
    route = respx.get(f"{BASE}/projects/{PROJECT}/services/svc-fork").mock(
        side_effect=[
            httpx.Response(200, json=service_json("svc-fork", "QUEUED")),
            httpx.Response(200, json=service_json("svc-fork", "CONFIGURING")),
            httpx.Response(200, json=service_json("svc-fork", "READY")),
        ]
    )
    seen: list[str] = []

    svc = tiger.wait_ready("svc-fork", timeout=60, interval=5, on_status=lambda s, t: seen.append(s.status))

    assert svc.ready and svc.status == "READY"
    assert route.call_count == 3
    assert ft.sleeps == [5, 5]
    assert seen == ["QUEUED", "CONFIGURING", "READY"]


@respx.mock
def test_wait_ready_keeps_initial_password_from_fork(tiger: TigerClient):
    respx.post(f"{BASE}/projects/{PROJECT}/services/{PRIMARY}/forkService").mock(
        return_value=httpx.Response(202, json=service_json("svc-fork", "QUEUED", initial_password="pw1"))
    )
    respx.get(f"{BASE}/projects/{PROJECT}/services/svc-fork").mock(
        return_value=httpx.Response(200, json=service_json("svc-fork", "READY"))  # no password on GET
    )
    forked = tiger.fork(PRIMARY, "audit-1-0")
    ready = tiger.wait_ready(forked, timeout=10, interval=1)
    assert ready.initial_password == "pw1"
    assert (
        tiger.connection_url(ready)
        == "postgres://tsdbadmin:pw1@svc-fork.tsdb.cloud:34567/tsdb?sslmode=require"
    )


@respx.mock
def test_wait_ready_times_out(tiger: TigerClient, ft: FakeTime):
    route = respx.get(f"{BASE}/projects/{PROJECT}/services/svc-fork").mock(
        return_value=httpx.Response(200, json=service_json("svc-fork", "QUEUED"))
    )
    with pytest.raises(TigerTimeout, match="QUEUED"):
        tiger.wait_ready("svc-fork", timeout=20, interval=5)
    # polls at t=0,5,10,15,20; at 20 the next sleep would overshoot the timeout, so it gives up
    assert route.call_count == 5
    assert ft.now == 20


@respx.mock
def test_wait_ready_raises_on_failed_state(tiger: TigerClient):
    respx.get(f"{BASE}/projects/{PROJECT}/services/svc-fork").mock(
        return_value=httpx.Response(200, json=service_json("svc-fork", "FAILED"))
    )
    with pytest.raises(TigerForkFailed):
        tiger.wait_ready("svc-fork", timeout=10, interval=1)


@respx.mock
def test_delete_sends_delete(tiger: TigerClient):
    route = respx.delete(f"{BASE}/projects/{PROJECT}/services/svc-fork").mock(
        return_value=httpx.Response(202)
    )
    tiger.delete("svc-fork")
    assert route.called and route.calls.last.request.method == "DELETE"


@respx.mock
def test_delete_all_forks_only_touches_prefix(tiger: TigerClient):
    respx.get(f"{BASE}/projects/{PROJECT}/services").mock(
        return_value=httpx.Response(
            200,
            json=[
                service_json(PRIMARY, "READY", name="tempo-primary"),
                service_json("f1", "READY", name="audit-7--2"),
                service_json("f2", "CONFIGURING", name="audit-7-+1"),
                service_json("other", "READY", name="girik-scratch"),
            ],
        )
    )
    deleted_routes = {
        sid: respx.delete(f"{BASE}/projects/{PROJECT}/services/{sid}").mock(return_value=httpx.Response(202))
        for sid in (PRIMARY, "f1", "f2", "other")
    }
    deleted = tiger.delete_all_forks(prefix="audit-")
    assert sorted(deleted) == ["f1", "f2"]
    assert deleted_routes["f1"].called and deleted_routes["f2"].called
    assert not deleted_routes[PRIMARY].called and not deleted_routes["other"].called


@respx.mock
def test_list_services_accepts_wrapped_payload(tiger: TigerClient):
    respx.get(f"{BASE}/projects/{PROJECT}/services").mock(
        return_value=httpx.Response(200, json={"services": [service_json("a", "READY", name="a")]})
    )
    assert [s.service_id for s in tiger.list_services()] == ["a"]


def test_connection_url_needs_endpoint():
    svc = Service(service_id="x", name="x", status="QUEUED", initial_password="pw")
    with pytest.raises(TigerError, match="no endpoint"):
        TigerClient.connection_url(svc)


def test_constructor_rejects_blank_credentials():
    with pytest.raises(ValueError):
        TigerClient("", "k", "s")
