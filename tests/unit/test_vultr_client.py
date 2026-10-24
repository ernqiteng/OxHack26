"""VultrClient against a mocked Vultr v2 API (respx). No network."""

import httpx
import pytest
import respx

from tempo.infra.vultr import NoIdleWorker, VultrClient, VultrError, VultrTimeout

BASE = "https://vultr.test/v2"


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, s: float) -> None:
        self.now += s

    def clock(self) -> float:
        return self.now


@pytest.fixture
def ft() -> FakeTime:
    return FakeTime()


@pytest.fixture
def vultr(ft: FakeTime) -> VultrClient:
    http = httpx.Client(base_url=BASE, headers={"Authorization": "Bearer tok"})
    return VultrClient("tok", client=http, sleep=ft.sleep, clock=ft.clock)


def instance(
    id_: str, label: str, status: str = "active", tags=("tempo-worker",), power="running", ip="10.0.0.1"
):
    return {
        "id": id_,
        "label": label,
        "status": status,
        "power_status": power,
        "server_status": "ok",
        "main_ip": ip,
        "region": "ewr",
        "plan": "vc2-1c-1gb",
        "tags": list(tags),
    }


def page(instances, next_cursor=""):
    return {
        "instances": instances,
        "meta": {"total": len(instances), "links": {"next": next_cursor, "prev": ""}},
    }


@respx.mock
def test_list_workers_filters_by_tag(vultr: VultrClient):
    route = respx.get(f"{BASE}/instances").mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    instance("i2", "tempo-worker-2"),
                    instance("b", "tempo-backend", tags=("tempo", "backend")),
                    instance("i1", "tempo-worker-1"),
                ]
            ),
        )
    )
    workers = vultr.list_workers()
    assert [w.label for w in workers] == ["tempo-worker-1", "tempo-worker-2"]
    assert route.calls.last.request.url.params["tag"] == "tempo-worker"
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_list_workers_follows_pagination(vultr: VultrClient):
    route = respx.get(f"{BASE}/instances").mock(
        side_effect=[
            httpx.Response(200, json=page([instance("i1", "tempo-worker-1")], next_cursor="abc")),
            httpx.Response(200, json=page([instance("i2", "tempo-worker-2")])),
        ]
    )
    assert [w.instance_id for w in vultr.list_workers()] == ["i1", "i2"]
    assert route.call_count == 2
    assert route.calls[1].request.url.params["cursor"] == "abc"


@respx.mock
def test_pick_idle_returns_active_unleased_worker(vultr: VultrClient):
    respx.get(f"{BASE}/instances").mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    instance("i1", "tempo-worker-1", status="pending"),
                    instance("i2", "tempo-worker-2"),
                    instance("i3", "tempo-worker-3", power="stopped"),
                    instance("i4", "tempo-worker-4"),
                ]
            ),
        )
    )
    first = vultr.pick_idle()
    assert first.instance_id == "i2"
    vultr.mark_busy(first, "audit-1-0")
    second = vultr.pick_idle()
    assert second.instance_id == "i4"
    vultr.mark_busy(second, "audit-1-+1")
    with pytest.raises(NoIdleWorker) as exc:
        vultr.pick_idle()
    msg = str(exc.value)
    assert "no idle worker" in msg
    assert "tempo-worker-1=pending" in msg
    assert "busy:audit-1-0" in msg
    vultr.mark_idle(first)
    assert vultr.pick_idle().instance_id == "i2"


@respx.mock
def test_pick_idle_with_no_workers_has_clear_error(vultr: VultrClient):
    respx.get(f"{BASE}/instances").mock(return_value=httpx.Response(200, json=page([])))
    with pytest.raises(NoIdleWorker, match="no instances tagged 'tempo-worker'"):
        vultr.pick_idle()


@respx.mock
def test_lease_releases_on_exception(vultr: VultrClient):
    respx.get(f"{BASE}/instances").mock(
        return_value=httpx.Response(200, json=page([instance("i1", "tempo-worker-1")]))
    )
    with pytest.raises(RuntimeError), vultr.lease("job"):
        assert vultr.busy_jobs() == {"i1": "job"}
        raise RuntimeError("worker blew up")
    assert vultr.busy_jobs() == {}
    assert vultr.pick_idle().instance_id == "i1"


@respx.mock
def test_create_instance_posts_snapshot_body(vultr: VultrClient):
    route = respx.post(f"{BASE}/instances").mock(
        return_value=httpx.Response(
            202, json={"instance": instance("new", "tempo-worker-5", status="pending")}
        )
    )
    w = vultr.create_instance(
        "tempo-worker-5",
        region="ewr",
        plan="vc2-1c-1gb",
        snapshot_id="snap-1",
        sshkey_ids=["key-1"],
        tags=["tempo-worker"],
    )
    import json

    assert json.loads(route.calls.last.request.content) == {
        "region": "ewr",
        "plan": "vc2-1c-1gb",
        "label": "tempo-worker-5",
        "hostname": "tempo-worker-5",
        "snapshot_id": "snap-1",
        "sshkey_id": ["key-1"],
        "tags": ["tempo-worker"],
    }
    assert w.instance_id == "new" and w.status == "pending"


def test_create_instance_needs_image(vultr: VultrClient):
    with pytest.raises(ValueError):
        vultr.create_instance("x", region="ewr", plan="vc2-1c-1gb")


@respx.mock
def test_wait_active_polls_then_times_out(vultr: VultrClient, ft: FakeTime):
    pending = instance("i1", "w", status="pending")
    pending["server_status"] = "installingbooting"
    respx.get(f"{BASE}/instances/i1").mock(return_value=httpx.Response(200, json={"instance": pending}))
    with pytest.raises(VultrTimeout):
        vultr.wait_active("i1", timeout=30, interval=10)
    assert ft.now == 30  # polled at 0, 10, 20, 30


@respx.mock
def test_wait_active_returns_when_ok(vultr: VultrClient):
    booting = instance("i1", "w", status="active")
    booting["server_status"] = "installingbooting"
    respx.get(f"{BASE}/instances/i1").mock(
        side_effect=[
            httpx.Response(200, json={"instance": booting}),
            httpx.Response(200, json={"instance": instance("i1", "w")}),
        ]
    )
    assert vultr.wait_active("i1", timeout=60, interval=1).server_status == "ok"


@respx.mock
def test_http_error_is_wrapped(vultr: VultrClient):
    respx.get(f"{BASE}/instances").mock(return_value=httpx.Response(401, json={"error": "Invalid API token"}))
    with pytest.raises(VultrError, match="401"):
        vultr.list_workers()
