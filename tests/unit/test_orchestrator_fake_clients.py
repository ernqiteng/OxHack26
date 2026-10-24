"""Fork-mode audit with a fake Tiger and a fake worker pool: naming, cleanup on every path, failed shifts,
timings and concurrency. No network, no DB."""

import threading
import time

import pytest

from tempo.audit.orchestrator import SHIFTS, AuditProgress, check_audit_rows, run_audit
from tempo.audit.pool import ReplayResult, WorkerError, WorkerSlot
from tempo.infra.tiger import Service

PNL = {-2: 90.0, -1: 101.5, 0: 110.0, 1: 96.0, 2: 80.25}


def shift_of(name: str) -> int | str:
    tail = name.split("-", 2)[2]
    return tail if tail == "all" else int(tail)


class FakeTiger:
    def __init__(self, fail_fork=(), slow_ready=(), ready_delay=0.2, leftovers=(), fail_delete=()):
        self.fail_fork, self.slow_ready, self.ready_delay = set(fail_fork), set(slow_ready), ready_delay
        self.fail_delete = set(fail_delete)
        self.forked: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []
        self.extra = [Service(service_id=f"x-{n}", name=n, status="READY") for n in leftovers]
        self.lock = threading.Lock()

    def fork(self, parent, name, fork_strategy="NOW"):
        if shift_of(name) in self.fail_fork:
            raise RuntimeError("fork quota exceeded")
        with self.lock:
            self.forked.append((parent, name, fork_strategy))
        return Service(
            service_id=f"svc{name}", name=name, status="QUEUED", host="h", port=1, initial_password="pw"
        )

    def wait_ready(self, svc, timeout=180, interval=2):
        time.sleep(5 if shift_of(svc.name) in self.slow_ready else self.ready_delay)
        return Service(svc.service_id, svc.name, "READY", "h", 1, svc.initial_password)

    @staticmethod
    def connection_url(svc):
        return f"fake://{svc.name}"

    def delete(self, service_id):
        if any(service_id.endswith(f"-{s}") for s in self.fail_delete):
            raise RuntimeError("delete 503")
        with self.lock:
            self.deleted.append(service_id)

    def list_services(self):
        return [s for s in self.extra if s.service_id not in self.deleted]


class FakePool:
    def __init__(self, fail=(), delay=0.05):
        self.fail, self.delay = set(fail), delay
        self.calls = []

    async def replay(self, dsn, decision_id, shift, run_id, *, on_assigned=None):
        import asyncio
        from datetime import UTC, datetime

        slot = WorkerSlot(f"tempo-worker-{SHIFTS.index(shift) + 1}", "http://x", "ewr")
        if on_assigned:
            on_assigned(slot)
        self.calls.append((dsn, decision_id, shift, run_id))
        await asyncio.sleep(self.delay)
        if shift in self.fail:
            raise WorkerError(f"{slot.worker_id} -> 500: worker died")
        now = datetime.now(tz=UTC)
        return ReplayResult(PNL[shift], slot.worker_id, now, now)


def audit(tiger, pool, forks="per_shift", **kw):
    return run_audit(
        None,
        7,
        mode="fork",
        write=False,
        tiger=tiger,
        pool=pool,
        parent_service_id="primary",
        connectable=lambda dsn, t: None,
        forks=forks,
        **kw,
    )


def test_five_forks_named_dispatched_and_deleted():
    tiger, pool = FakeTiger(), FakePool()
    progress = AuditProgress()
    rows = audit(tiger, pool, progress=progress)

    check_audit_rows(rows)
    assert sorted(n for _, n, _ in tiger.forked) == sorted(f"audit-7-{s}" for s in SHIFTS)
    assert {p for p, _, _ in tiger.forked} == {"primary"}
    assert {st for _, _, st in tiger.forked} == {"NOW"}
    assert sorted(tiger.deleted) == sorted(f"svcaudit-7-{s}" for s in SHIFTS)
    assert {c[0] for c in pool.calls} == {f"fake://audit-7-{s}" for s in SHIFTS}
    assert all(c[3] == f"audit-7-{c[2]}" for c in pool.calls)
    assert [r.pnl_delta_gbp for r in rows] == [-20.0, -8.5, 0.0, -14.0, -29.75]
    assert all(r.mode == "fork" and r.fork_service_id and r.worker_id for r in rows)
    assert all(r.finished_at >= r.started_at and r.elapsed_s >= 0.2 for r in rows)
    states, events = progress.snapshot()
    assert set(states.values()) == {"done"} and progress.finished
    assert events[-1].message == "5/5 done, forks deleted"
    assert any("dispatched to tempo-worker-3 (ewr)" in e.message for e in events)


def test_forks_run_concurrently():
    t0 = time.monotonic()
    audit(FakeTiger(ready_delay=0.5), FakePool())
    assert time.monotonic() - t0 < 1.5  # five 0.5 s waits in parallel, not 2.5 s in series


def test_worker_failure_keeps_other_shifts_and_deletes_every_fork():
    tiger = FakeTiger()
    rows = audit(tiger, FakePool(fail={1}))
    check_audit_rows(rows)
    failed = [r for r in rows if r.failed]
    assert [r.shift for r in failed] == [1]
    assert "worker died" in failed[0].error and failed[0].pnl_delta_gbp is None
    assert failed[0].fork_service_id == "svcaudit-7-1" and failed[0].worker_id == "tempo-worker-4"
    assert len(tiger.deleted) == 5


def test_fork_failure_is_a_failed_shift_not_a_crash():
    tiger = FakeTiger(fail_fork={-2})
    rows = audit(tiger, FakePool())
    assert [r.shift for r in rows if r.failed] == [-2]
    assert "fork quota exceeded" in rows[0].error and rows[0].fork_service_id is None
    assert len(tiger.deleted) == 4


def test_shift_timeout_marks_failed_and_still_deletes():
    tiger = FakeTiger(slow_ready={2})
    t0 = time.monotonic()
    rows = audit(tiger, FakePool(), shift_timeout=1.0)
    assert time.monotonic() - t0 < 4  # did not wait for the 5 s ready
    assert [r.shift for r in rows if r.failed] == [2]
    assert "timed out after 1s" in rows[4].error
    assert "svcaudit-7-2" in tiger.deleted and len(tiger.deleted) == 5


def test_failed_shift_zero_nulls_deltas():
    rows = audit(FakeTiger(), FakePool(fail={0}))
    check_audit_rows(rows)
    assert all(r.pnl_delta_gbp is None for r in rows)


def test_sweep_deletes_leftovers_for_this_decision_only():
    tiger = FakeTiger(leftovers=["audit-7-orphan", "audit-70-1", "tempo-primary"])
    progress = AuditProgress()
    audit(tiger, FakePool(), progress=progress)
    assert "x-audit-7-orphan" in tiger.deleted
    assert "x-audit-70-1" not in tiger.deleted and "x-tempo-primary" not in tiger.deleted
    assert any("swept leftover fork audit-7-orphan" in m for m in progress.log_lines())


def test_delete_failure_is_logged_not_raised():
    tiger = FakeTiger(fail_delete={-1})
    progress = AuditProgress()
    rows = audit(tiger, FakePool(), progress=progress)
    assert not any(r.failed for r in rows)
    assert any("delete svcaudit-7--1 failed" in m for m in progress.log_lines())


def test_missing_parent_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("TIGER_PRIMARY_SERVICE_ID", "")
    from tempo.config import settings

    settings.cache_clear()
    with pytest.raises(ValueError, match="no parent service"):
        run_audit(None, 7, mode="fork", write=False, tiger=FakeTiger(), pool=FakePool())
    settings.cache_clear()


# -- shared layout: one fork per audit (fits the free tier's 2-service limit) -----------------------


def test_shared_uses_one_fork_five_workers_one_delete():
    tiger, pool = FakeTiger(), FakePool()
    progress = AuditProgress()
    rows = audit(tiger, pool, forks="shared", progress=progress)
    check_audit_rows(rows)
    assert [n for _, n, _ in tiger.forked] == ["audit-7-all"]
    assert tiger.deleted == ["svcaudit-7-all"]
    assert {c[0] for c in pool.calls} == {"fake://audit-7-all"}
    assert sorted(c[3] for c in pool.calls) == sorted(f"audit-7-{s}" for s in SHIFTS)  # own run_ids
    assert {r.fork_service_id for r in rows} == {"svcaudit-7-all"}
    assert len({r.worker_id for r in rows}) == 5
    assert set(progress.snapshot()[0].values()) == {"done"}


def test_shared_fork_failure_fails_all_five_cleanly():
    tiger = FakeTiger(fail_fork={"all"})
    rows = audit(tiger, FakePool(), forks="shared")
    assert all(r.failed and "fork quota exceeded" in r.error for r in rows)
    assert tiger.deleted == []
    check_audit_rows(rows)


def test_shared_one_worker_failure_keeps_the_rest():
    tiger = FakeTiger()
    rows = audit(tiger, FakePool(fail={-1}), forks="shared")
    assert [r.shift for r in rows if r.failed] == [-1]
    assert rows[1].fork_service_id == "svcaudit-7-all"
    assert tiger.deleted == ["svcaudit-7-all"]


def test_shared_slow_fork_times_out_every_shift_and_still_deletes():
    tiger = FakeTiger(slow_ready={"all"})
    t0 = time.monotonic()
    rows = audit(tiger, FakePool(), forks="shared", shift_timeout=1.0)
    assert time.monotonic() - t0 < 4
    assert all(r.failed and "timed out" in r.error for r in rows)
    assert tiger.deleted == ["svcaudit-7-all"]


def test_default_layout_comes_from_settings(monkeypatch):
    from tempo.config import settings

    monkeypatch.setenv("TEMPO_AUDIT_FORKS", "shared")
    settings.cache_clear()
    tiger = FakeTiger()
    run_audit(
        None,
        7,
        mode="fork",
        write=False,
        tiger=tiger,
        pool=FakePool(),
        parent_service_id="p",
        connectable=lambda d, t: None,
    )
    assert [n for _, n, _ in tiger.forked] == ["audit-7-all"]
    settings.cache_clear()


def test_unknown_layout_rejected():
    with pytest.raises(ValueError, match="forks must be one of"):
        audit(FakeTiger(), FakePool(), forks="many")
