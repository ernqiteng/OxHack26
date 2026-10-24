"""TigerClient: fork(), wait_ready(), delete(), connection_url(), delete_all_forks().

Tiger Cloud REST, HTTP Basic auth.

Owner: Ayo. See docs/ayo.md and docs/needs.md section B2.

Endpoints (base https://console.cloud.tigerdata.com/public/api/v1, HTTP Basic auth access_key:secret_key):

    GET    /projects/{project_id}/services
    GET    /projects/{project_id}/services/{service_id}
    POST   /projects/{project_id}/services/{service_id}/forkService   {fork_strategy, name, environment_tag}
    DELETE /projects/{project_id}/services/{service_id}

A fork response carries `service_id`, `name`, `status`, `endpoint.host`, `endpoint.port` and
`initial_password`.
The password is only returned once, on creation, so `fork()` keeps it on the returned `Service` and
`wait_ready()` copies it forward when you pass the original `Service` instead of a bare id.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://console.cloud.tigerdata.com/public/api/v1"
READY = "READY"
FORKABLE_STATES = {"READY", "PAUSED"}
_FAILED_MARKERS = ("FAIL", "ERROR", "DELET")


class TigerError(Exception):
    """Base class for Tiger client errors."""


class TigerTimeout(TigerError):
    """wait_ready gave up before the service became READY."""


class TigerForkFailed(TigerError):
    """The service entered a failed or deleted state while we were waiting for it."""


@dataclass
class Service:
    service_id: str
    name: str
    status: str
    host: str | None = None
    port: int | None = None
    initial_password: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Service:
        endpoint = data.get("endpoint") or {}
        port = endpoint.get("port")
        return cls(
            service_id=str(data.get("service_id") or data.get("id") or ""),
            name=str(data.get("name") or ""),
            status=str(data.get("status") or "").upper(),
            host=endpoint.get("host"),
            port=int(port) if port else None,
            initial_password=data.get("initial_password"),
            raw=data,
        )

    @property
    def ready(self) -> bool:
        return self.status == READY

    @property
    def failed(self) -> bool:
        return any(marker in self.status for marker in _FAILED_MARKERS)


class TigerClient:
    """Thin, synchronous client over the Tiger Cloud public REST API.

    Pass `client=` to supply your own `httpx.Client` (tests do this with respx); `base_url` is then ignored.
    `sleep` and `clock` are injectable so `wait_ready` can be tested without waiting.
    """

    def __init__(
        self,
        project_id: str,
        access_key: str,
        secret_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not project_id or not access_key or not secret_key:
            raise ValueError("TigerClient needs project_id, access_key and secret_key (docs/needs.md B1)")
        self.project_id = project_id
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(access_key, secret_key),
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "tempo-oxhack26"},
        )
        self._sleep = sleep
        self._clock = clock

    @classmethod
    def from_env(cls, **kwargs: Any) -> TigerClient:
        from tempo.config import settings

        t = settings().tiger
        if not t.configured:
            raise RuntimeError(
                "Tiger credentials missing: set TIGERDATA_PROJECT_ID/ACCESS_KEY/SECRET_KEY in .env"
            )
        kwargs.setdefault("base_url", t.base_url)
        return cls(t.project_id, t.access_key, t.secret_key, **kwargs)  # type: ignore[arg-type]

    # -- HTTP plumbing -------------------------------------------------------------------------

    def _path(self, service_id: str | None = None, suffix: str = "") -> str:
        base = f"/projects/{self.project_id}/services"
        if service_id:
            base += f"/{service_id}"
        return base + suffix

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise TigerError(f"{method} {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise TigerError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp

    @staticmethod
    def _service_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("services", "data", "items"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        raise TigerError(f"unexpected list payload: {str(payload)[:200]}")

    # -- Public API ------------------------------------------------------------------------------

    def list_services(self) -> list[Service]:
        resp = self._request("GET", self._path())
        return [Service.from_api(item) for item in self._service_list(resp.json())]

    def get(self, service_id: str) -> Service:
        resp = self._request("GET", self._path(service_id))
        return Service.from_api(resp.json())

    def fork(
        self,
        service_id: str,
        name: str,
        *,
        fork_strategy: str = "NOW",
        environment_tag: str = "DEV",
    ) -> Service:
        """Fork `service_id` into a new service called `name`. Returns immediately; call wait_ready next.

        `fork_strategy` is "NOW" (fresh snapshot, what the timing audit needs) or "LAST_SNAPSHOT" (faster,
        up to an hour stale). The parent must be READY or PAUSED.
        """
        body = {"fork_strategy": fork_strategy, "name": name, "environment_tag": environment_tag}
        resp = self._request("POST", self._path(service_id, "/forkService"), json=body)
        svc = Service.from_api(resp.json())
        if not svc.service_id:
            raise TigerError(f"fork response had no service_id: {resp.text[:300]}")
        return svc

    def wait_ready(
        self,
        service: Service | str,
        *,
        timeout: float = 180.0,
        interval: float = 5.0,
        on_status: Callable[[Service, float], None] | None = None,
    ) -> Service:
        """Poll until the service is READY. Raises TigerTimeout after `timeout` seconds, TigerForkFailed
        if it enters a failed/deleted state. Pass the `Service` from fork() to keep its initial_password.
        """
        original = service if isinstance(service, Service) else None
        service_id = service.service_id if isinstance(service, Service) else service
        start = self._clock()
        last_status = None
        while True:
            svc = self.get(service_id)
            if original is not None and svc.initial_password is None:
                svc.initial_password = original.initial_password
            elapsed = self._clock() - start
            if svc.status != last_status:
                last_status = svc.status
                if on_status is not None:
                    on_status(svc, elapsed)
            if svc.ready:
                return svc
            if svc.failed:
                raise TigerForkFailed(f"service {service_id} entered state {svc.status} after {elapsed:.0f}s")
            if elapsed + interval > timeout:
                raise TigerTimeout(
                    f"service {service_id} still {svc.status} after {elapsed:.0f}s (timeout {timeout:.0f}s)"
                )
            self._sleep(interval)

    def delete(self, service_id: str) -> None:
        self._request("DELETE", self._path(service_id))

    @staticmethod
    def connection_url(
        service: Service,
        *,
        password: str | None = None,
        user: str = "tsdbadmin",
        database: str = "tsdb",
        sslmode: str = "require",
    ) -> str:
        """Build the DSN for a service. Uses `service.initial_password` unless `password` is given."""
        pw = password or service.initial_password
        if not service.host or not service.port:
            raise TigerError(f"service {service.service_id} has no endpoint yet (status {service.status})")
        if not pw:
            raise TigerError(f"no password for service {service.service_id}; pass password= explicitly")
        return f"postgres://{user}:{pw}@{service.host}:{service.port}/{database}?sslmode={sslmode}"

    def delete_all_forks(self, prefix: str = "audit-") -> list[str]:
        """Delete every service whose name starts with `prefix`. Returns the deleted ids. Never touches
        services with other names, so the primary is safe as long as it is not called `audit-...`."""
        deleted: list[str] = []
        for svc in self.list_services():
            if svc.name.startswith(prefix):
                self.delete(svc.service_id)
                deleted.append(svc.service_id)
        return deleted

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TigerClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
