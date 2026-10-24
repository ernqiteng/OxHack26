"""Worker pools: leasing, queueing when workers < jobs, error mapping, Vultr discovery."""

import asyncio

from fastapi import FastAPI, HTTPException

from tempo.audit.pool import HttpWorkerPool, LocalWorkerPool, NoWorkers, WorkerError
from tempo.infra.vultr import Worker


def stub_app(delay=0.1, fail_shift=None):
    app = FastAPI()
    app.state.active = 0
    app.state.peak = 0

    @app.post("/replay")
    async def replay(body: dict):
        app.state.active += 1
        app.state.peak = max(app.state.peak, app.state.active)
        await asyncio.sleep(delay)
        app.state.active -= 1
        if body["shift"] == fail_shift:
            raise HTTPException(500, "replay crashed: boom")
        return {
            "pnl_gbp": 10.0 * body["shift"],
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:01+00:00",
            "worker_id": "host",
            "simulator": "ref",
        }

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def run_all(pool, shifts):
    async def go():
        return await asyncio.gather(
            *(pool.replay("dsn", 1, s, f"r{s}") for s in shifts), return_exceptions=True
        )

    return asyncio.run(go())


def test_two_workers_serve_five_jobs_two_at_a_time():
    app = stub_app()
    pool = LocalWorkerPool(2, app=app)
    results = run_all(pool, [-2, -1, 0, 1, 2])
    assert [r.pnl_gbp for r in results] == [-20.0, -10.0, 0.0, 10.0, 20.0]
    assert app.state.peak == 2
    assert {r.worker_id for r in results} == {"local-1", "local-2"}


def test_worker_error_carries_detail_and_frees_the_slot():
    pool = LocalWorkerPool(1, app=stub_app(fail_shift=1))
    results = run_all(pool, [1, 0])
    assert isinstance(results[0], WorkerError) and "replay crashed: boom" in str(results[0])
    assert results[1].pnl_gbp == 0.0


def test_pool_survives_a_second_event_loop():
    pool = LocalWorkerPool(1, app=stub_app(delay=0))
    assert run_all(pool, [1])[0].pnl_gbp == 10.0
    assert run_all(pool, [2])[0].pnl_gbp == 20.0


def test_health_checks_every_worker():
    pool = LocalWorkerPool(3, app=stub_app())
    health = asyncio.run(pool.health())
    assert set(health) == {"local-1", "local-2", "local-3"} and all(ok for ok, _ in health.values())


def test_unreachable_worker_is_worker_error():
    pool = HttpWorkerPool(
        [__import__("tempo.audit.pool", fromlist=["WorkerSlot"]).WorkerSlot("w", "http://127.0.0.1:1")]
    )
    result = run_all(pool, [0])[0]
    assert isinstance(result, WorkerError) and "w:" in str(result)


class FakeVultr:
    def __init__(self, workers):
        self.workers = workers

    def list_workers(self):
        return self.workers


def vw(label, status="active", ip="1.2.3.4"):
    return Worker(label, label, status, "running", "ok", ip, "ewr", "vc2-1c-1gb", ["tempo-worker"])


def test_from_vultr_uses_active_workers_only():
    pool = HttpWorkerPool.from_vultr(
        FakeVultr(
            [vw("tempo-worker-1"), vw("tempo-worker-2", status="pending"), vw("tempo-worker-3", ip="0.0.0.0")]
        )
    )
    assert [(w.worker_id, w.base_url, w.region) for w in pool.workers] == [
        ("tempo-worker-1", "http://1.2.3.4:8000", "ewr")
    ]


def test_from_vultr_with_no_workers_raises():
    try:
        HttpWorkerPool.from_vultr(FakeVultr([]))
    except NoWorkers as exc:
        assert "tempo-worker" in str(exc)
    else:
        raise AssertionError("expected NoWorkers")
