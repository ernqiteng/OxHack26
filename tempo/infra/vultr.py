"""VultrClient: list_workers(), pick_idle(), create from snapshot. Bearer auth, 30 req/s.

Owner: Ayo. See docs/ayo.md and docs/needs.md section B4.

The worker pool is pre-warmed: five instances tagged `tempo-worker` run all day and the click dispatches
HTTP jobs to them. "Idle" therefore means "Vultr says active and this process has not leased it to a job",
tracked in memory by this client (`lease()` / `mark_busy()` / `mark_idle()`).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.vultr.com/v2"
WORKER_TAG = "tempo-worker"
WORKER_PORT = 8000


class VultrError(Exception):
    """Base class for Vultr client errors."""


class NoIdleWorker(VultrError):
    """Every tagged worker is either not active or already leased to a job."""


class VultrTimeout(VultrError):
    """wait_active gave up."""


@dataclass
class Worker:
    instance_id: str
    label: str
    status: str
    power_status: str
    server_status: str
    main_ip: str
    region: str
    plan: str
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Worker:
        tags = list(data.get("tags") or [])
        legacy_tag = data.get("tag")
        if legacy_tag and legacy_tag not in tags:
            tags.append(legacy_tag)
        return cls(
            instance_id=str(data.get("id") or ""),
            label=str(data.get("label") or ""),
            status=str(data.get("status") or ""),
            power_status=str(data.get("power_status") or ""),
            server_status=str(data.get("server_status") or ""),
            main_ip=str(data.get("main_ip") or ""),
            region=str(data.get("region") or ""),
            plan=str(data.get("plan") or ""),
            tags=tags,
            raw=data,
        )

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.power_status != "stopped"

    def base_url(self, port: int = WORKER_PORT) -> str:
        return f"http://{self.main_ip}:{port}"


class VultrClient:
    """Synchronous client for the parts of the Vultr v2 API that Tempo uses.

    Pass `client=` to supply your own `httpx.Client` (tests do this with respx); `base_url` is then ignored.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        worker_tag: str = WORKER_TAG,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError("VultrClient needs an api_key (VULTR_API_KEY, docs/needs.md B1)")
        self.worker_tag = worker_tag
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "tempo-oxhack26",
            },
            timeout=timeout,
        )
        self._sleep = sleep
        self._clock = clock
        self._busy: dict[str, str] = {}  # instance_id -> job label

    @classmethod
    def from_env(cls, **kwargs: Any) -> VultrClient:
        from tempo.config import settings

        v = settings().vultr
        if not v.configured:
            raise RuntimeError("VULTR_API_KEY is not set in .env")
        kwargs.setdefault("base_url", v.base_url)
        return cls(v.api_key, **kwargs)  # type: ignore[arg-type]

    # -- HTTP plumbing -------------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise VultrError(f"{method} {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise VultrError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp

    def _paginate(self, path: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Follow Vultr's `meta.links.next` cursor until exhausted."""
        items: list[dict[str, Any]] = []
        params = dict(params or {})
        params.setdefault("per_page", 100)
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            payload = self._request("GET", path, params=params).json()
            items.extend(payload.get(key) or [])
            cursor = ((payload.get("meta") or {}).get("links") or {}).get("next") or None
            if not cursor:
                return items

    # -- Instances -------------------------------------------------------------------------------

    def list_instances(self, tag: str | None = None) -> list[dict[str, Any]]:
        params = {"tag": tag} if tag else None
        return self._paginate("/instances", "instances", params)

    def get_instance(self, instance_id: str) -> Worker:
        return Worker.from_api(self._request("GET", f"/instances/{instance_id}").json()["instance"])

    def list_workers(self) -> list[Worker]:
        """Instances carrying the worker tag, sorted by label. Filtered client-side as well as by the
        `tag` query parameter, so an API that ignores the parameter still gives the right answer."""
        workers = [Worker.from_api(item) for item in self.list_instances(tag=self.worker_tag)]
        workers = [w for w in workers if self.worker_tag in w.tags]
        return sorted(workers, key=lambda w: w.label)

    def create_instance(
        self,
        label: str,
        *,
        region: str,
        plan: str,
        snapshot_id: str | None = None,
        os_id: int | None = None,
        sshkey_ids: list[str] | None = None,
        user_data_b64: str | None = None,
        tags: list[str] | None = None,
        hostname: str | None = None,
    ) -> Worker:
        if not snapshot_id and not os_id:
            raise ValueError("create_instance needs snapshot_id or os_id")
        body: dict[str, Any] = {"region": region, "plan": plan, "label": label, "hostname": hostname or label}
        if snapshot_id:
            body["snapshot_id"] = snapshot_id
        if os_id:
            body["os_id"] = os_id
        if sshkey_ids:
            body["sshkey_id"] = sshkey_ids
        if user_data_b64:
            body["user_data"] = user_data_b64
        if tags:
            body["tags"] = tags
        return Worker.from_api(self._request("POST", "/instances", json=body).json()["instance"])

    def delete_instance(self, instance_id: str) -> None:
        self._request("DELETE", f"/instances/{instance_id}")

    def wait_active(
        self,
        instance_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 10.0,
        on_status: Callable[[Worker, float], None] | None = None,
    ) -> Worker:
        """Poll until status == active and server_status == ok (or active with no server_status reported)."""
        start = self._clock()
        last: tuple[str, str, str] | None = None
        while True:
            w = self.get_instance(instance_id)
            elapsed = self._clock() - start
            state = (w.status, w.power_status, w.server_status)
            if state != last:
                last = state
                if on_status is not None:
                    on_status(w, elapsed)
            if w.status == "active" and w.server_status in ("ok", "", "none") and w.power_status == "running":
                return w
            if elapsed + interval > timeout:
                raise VultrTimeout(f"instance {instance_id} still {state} after {elapsed:.0f}s")
            self._sleep(interval)

    # -- Pool scheduling -------------------------------------------------------------------------

    def mark_busy(self, worker: Worker | str, job: str = "job") -> None:
        self._busy[worker.instance_id if isinstance(worker, Worker) else worker] = job

    def mark_idle(self, worker: Worker | str) -> None:
        self._busy.pop(worker.instance_id if isinstance(worker, Worker) else worker, None)

    def busy_jobs(self) -> dict[str, str]:
        return dict(self._busy)

    def pick_idle(self) -> Worker:
        """Return an active worker that is not leased. Raises NoIdleWorker with a per-worker state summary."""
        workers = self.list_workers()
        for w in workers:
            if w.is_active and w.instance_id not in self._busy:
                return w
        if not workers:
            raise NoIdleWorker(
                f"no instances tagged {self.worker_tag!r}; create the pool first (docs/ayo.md Phase 2)"
            )
        states = ", ".join(
            f"{w.label or w.instance_id}={w.status}/{w.power_status}"
            + (f" busy:{self._busy[w.instance_id]}" if w.instance_id in self._busy else "")
            for w in workers
        )
        raise NoIdleWorker(f"no idle worker among {len(workers)}: {states}")

    @contextmanager
    def lease(self, job: str = "job") -> Iterator[Worker]:
        """`with vultr.lease('audit-12-+1') as w:` picks an idle worker and releases it afterwards."""
        w = self.pick_idle()
        self.mark_busy(w, job)
        try:
            yield w
        finally:
            self.mark_idle(w)

    # -- Account, plans, images, keys -----------------------------------------------------------

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/account").json().get("account", {})

    def list_plans(self, plan_type: str | None = None) -> list[dict[str, Any]]:
        params = {"type": plan_type} if plan_type else None
        return self._paginate("/plans", "plans", params)

    def list_os(self) -> list[dict[str, Any]]:
        return self._paginate("/os", "os")

    def find_os_id(self, name_contains: str = "Ubuntu 24.04") -> int:
        for item in self.list_os():
            if name_contains.lower() in str(item.get("name", "")).lower() and "x64" in str(
                item.get("name", "")
            ):
                return int(item["id"])
        raise VultrError(f"no OS matching {name_contains!r}")

    def list_ssh_keys(self) -> list[dict[str, Any]]:
        return self._paginate("/ssh-keys", "ssh_keys")

    def create_ssh_key(self, name: str, public_key: str) -> dict[str, Any]:
        return self._request("POST", "/ssh-keys", json={"name": name, "ssh_key": public_key.strip()}).json()[
            "ssh_key"
        ]

    def create_snapshot(self, instance_id: str, description: str) -> dict[str, Any]:
        body = {"instance_id": instance_id, "description": description}
        return self._request("POST", "/snapshots", json=body).json()["snapshot"]

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return self._request("GET", f"/snapshots/{snapshot_id}").json()["snapshot"]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VultrClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
