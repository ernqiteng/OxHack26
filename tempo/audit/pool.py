"""Worker pools that the fork audit dispatches replays to.

Owner: Ayo. See docs/ayo.md Phase 2.

- `HttpWorkerPool`: workers addressed by base URL, one job per worker at a time. `from_vultr()` builds it from
  the instances tagged `tempo-worker` (the real pool).
- `LocalWorkerPool`: the same HTTP requests to the same worker app, served in-process through an ASGI
  transport. It is the stand-in until the Vultr pool exists, and what the equivalence tests use. Its worker
  ids are `local-1..n` so nobody mistakes it for Vultr on screen.

Both lease a free worker per job and wait (up to `acquire_timeout`) when all are busy, so five shifts on
three workers still complete.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

WORKER_PORT = 8000


class WorkerError(Exception):
    """A worker answered with an error, timed out, or could not be reached."""


class NoWorkers(WorkerError):
    """The pool has no workers at all."""


@dataclass
class ReplayResult:
    pnl_gbp: float
    worker_id: str
    started_at: datetime
    finished_at: datetime
    simulator: str | None = None


@dataclass
class WorkerSlot:
    worker_id: str
    base_url: str
    region: str | None = None


class HttpWorkerPool:
    kind = "http"

    def __init__(
        self,
        workers: list[WorkerSlot],
        *,
        client: httpx.AsyncClient | None = None,
        request_timeout: float = 150.0,
        acquire_timeout: float = 120.0,
        token: str | None = None,
    ) -> None:
        self.workers = list(workers)
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client
        self.request_timeout = request_timeout
        self.acquire_timeout = acquire_timeout
        self._free: asyncio.Queue[WorkerSlot] | None = None
        self._free_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def from_vultr(cls, vultr, *, port: int = WORKER_PORT, **kwargs) -> HttpWorkerPool:
        slots = [
            WorkerSlot(w.label or w.instance_id, f"http://{w.main_ip}:{port}", w.region)
            for w in vultr.list_workers()
            if w.is_active and w.main_ip and w.main_ip != "0.0.0.0"
        ]
        if not slots:
            raise NoWorkers(
                "no active instances tagged 'tempo-worker'; create the pool first (docs/ayo.md Phase 2)"
            )
        return cls(slots, **kwargs)

    def _queue(self) -> asyncio.Queue[WorkerSlot]:
        # One free-list per event loop: asyncio.run() makes a fresh loop for every audit.
        loop = asyncio.get_running_loop()
        if self._free is None or self._free_loop is not loop:
            self._free, self._free_loop = asyncio.Queue(), loop
            for w in self.workers:
                self._free.put_nowait(w)
        return self._free

    def _http(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=self.request_timeout)

    async def replay(
        self,
        database_url: str,
        decision_id: int,
        shift: int,
        run_id: str,
        *,
        on_assigned: Callable[[WorkerSlot], None] | None = None,
    ) -> ReplayResult:
        if not self.workers:
            raise NoWorkers("worker pool is empty")
        queue = self._queue()
        try:
            slot = await asyncio.wait_for(queue.get(), timeout=self.acquire_timeout)
        except TimeoutError as exc:
            raise WorkerError(f"no worker became free within {self.acquire_timeout:.0f}s") from exc
        try:
            if on_assigned:
                on_assigned(slot)
            body = {
                "database_url": database_url,
                "decision_id": decision_id,
                "shift": shift,
                "run_id": run_id,
            }
            client = self._http()
            try:
                resp = await client.post(
                    f"{slot.base_url}/replay", json=body, headers=self.headers, timeout=self.request_timeout
                )
            except httpx.HTTPError as exc:
                raise WorkerError(f"{slot.worker_id}: {type(exc).__name__}: {exc}") from exc
            finally:
                if client is not self._client:
                    await client.aclose()
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("detail", resp.text)
                except ValueError:
                    detail = resp.text
                raise WorkerError(f"{slot.worker_id} -> {resp.status_code}: {str(detail)[:300]}")
            data = resp.json()
            return ReplayResult(
                pnl_gbp=float(data["pnl_gbp"]),
                worker_id=slot.worker_id,
                started_at=datetime.fromisoformat(data["started_at"]),
                finished_at=datetime.fromisoformat(data["finished_at"]),
                simulator=data.get("simulator"),
            )
        finally:
            queue.put_nowait(slot)

    async def health(self, timeout: float = 5.0) -> dict[str, tuple[bool, str]]:
        """worker_id -> (ok, detail) for every worker, checked concurrently."""

        async def one(client: httpx.AsyncClient, slot: WorkerSlot) -> tuple[str, tuple[bool, str]]:
            try:
                resp = await client.get(f"{slot.base_url}/health", timeout=timeout)
                ok = resp.status_code == 200 and resp.json().get("ok") is True
                return slot.worker_id, (ok, resp.text[:200])
            except Exception as exc:  # noqa: BLE001
                return slot.worker_id, (False, f"{type(exc).__name__}: {exc}")

        client = self._http()
        try:
            return dict(await asyncio.gather(*(one(client, s) for s in self.workers)))
        finally:
            if client is not self._client:
                await client.aclose()


class LocalWorkerPool(HttpWorkerPool):
    """`n` in-process workers running the real worker app over an ASGI transport (no network)."""

    kind = "local"

    def __init__(self, n: int = 5, *, app=None, **kwargs) -> None:
        if app is None:
            from tempo.worker.main import app
        self.app = app
        if "token" not in kwargs:
            # The in-process worker reads TEMPO_WORKER_TOKEN from the same environment, so send it.
            from tempo.config import env

            kwargs["token"] = env("TEMPO_WORKER_TOKEN")
        slots = [WorkerSlot(f"local-{k}", f"http://local-{k}") for k in range(1, n + 1)]
        super().__init__(slots, **kwargs)

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), timeout=self.request_timeout)


def pool_from_urls(spec: str, token: str | None) -> HttpWorkerPool:
    """TEMPO_WORKER_URLS = 'tempo-worker-1=http://1.2.3.4:8000,tempo-worker-2=http://...' (or bare URLs)."""
    slots = []
    for k, item in enumerate(s.strip() for s in spec.split(",") if s.strip()):
        name, _, url = item.rpartition("=") if "=" in item else ("", "", item)
        slots.append(WorkerSlot(name or f"worker-{k + 1}", url.rstrip("/"), "ewr"))
    if not slots:
        raise NoWorkers("TEMPO_WORKER_URLS is set but empty")
    return HttpWorkerPool(slots, token=token)


def default_pool():
    """Pick the worker pool: Vultr's tagged instances when the API is reachable, else the static list in
    TEMPO_WORKER_URLS (written by scripts/create_workers.py; the backend box's IP is not in Vultr's API
    allow-list), else 5 local workers. Returns (pool, note)."""
    from tempo.config import env, settings

    token = env("TEMPO_WORKER_TOKEN")
    urls = env("TEMPO_WORKER_URLS")
    if settings().vultr.configured:
        from tempo.infra.vultr import VultrClient, VultrError

        try:
            with VultrClient.from_env() as vultr:
                pool = HttpWorkerPool.from_vultr(vultr, token=token)
            return pool, f"Vultr pool via API: {', '.join(w.worker_id for w in pool.workers)}"
        except (VultrError, NoWorkers) as exc:
            if not urls:
                raise
            note = f"Vultr API unavailable from here ({str(exc)[:80]}); using TEMPO_WORKER_URLS"
            return pool_from_urls(urls, token), note
    if urls:
        return pool_from_urls(urls, token), "VULTR_API_KEY not set; using TEMPO_WORKER_URLS"
    return LocalWorkerPool(5), "VULTR_API_KEY not set: replaying on 5 local workers (same worker code)"
