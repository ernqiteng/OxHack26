"""run_audit(conn, decision_id, mode='inprocess'|'fork'): five shifts, forks, workers, audits rows, cleanup.

Owner: Ayo. See docs/ayo.md Phase 1 task 2 (in-process) and Phase 2 task 4 (fork).

One shift failing never sinks the audit: its row is written with pnl_gbp NULL and `error` set on the
returned AuditRow, and the other shifts still render. pnl_delta_gbp = pnl[shift] - pnl[0]; if shift 0
itself failed, every delta is NULL.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tempo.audit.shifts import replay_shift

SHIFTS = (-2, -1, 0, 1, 2)
MODES = ("inprocess", "fork")


@dataclass
class AuditRow:
    decision_id: int
    shift: int
    pnl_gbp: float | None
    pnl_delta_gbp: float | None
    mode: str
    started_at: datetime
    finished_at: datetime
    fork_service_id: str | None = None
    worker_id: str | None = None
    audit_id: int | None = None
    error: str | None = None  # not stored; the audits table has no error column

    @property
    def failed(self) -> bool:
        return self.pnl_gbp is None

    @property
    def elapsed_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


def audit_run_id(decision_id: int, shift: int) -> str:
    return f"audit-{decision_id}-{shift}"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def fill_deltas(rows: list[AuditRow]) -> list[AuditRow]:
    base = next((r.pnl_gbp for r in rows if r.shift == 0), None)
    for r in rows:
        r.pnl_delta_gbp = None if base is None or r.pnl_gbp is None else r.pnl_gbp - base
    return rows


def write_audit_rows(conn, rows: list[AuditRow]) -> list[AuditRow]:
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """INSERT INTO audits (decision_id, shift, pnl_gbp, pnl_delta_gbp, mode, fork_service_id,
                                       worker_id, started_at, finished_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING audit_id""",
                (
                    r.decision_id,
                    r.shift,
                    r.pnl_gbp,
                    r.pnl_delta_gbp,
                    r.mode,
                    r.fork_service_id,
                    r.worker_id,
                    r.started_at,
                    r.finished_at,
                ),
            )
            r.audit_id = cur.fetchone()[0]
    return rows


def run_inprocess(
    conn,
    decision_id: int,
    *,
    replay: Callable[..., float] = replay_shift,
    on_progress: Callable[[AuditRow], None] | None = None,
    **replay_kwargs,
) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for shift in SHIFTS:
        started = _now()
        pnl, err = None, None
        try:
            pnl = float(replay(conn, decision_id, shift, audit_run_id(decision_id, shift), **replay_kwargs))
        except Exception as exc:  # noqa: BLE001 - one bad shift must not kill the view
            err = f"{type(exc).__name__}: {exc}"
        row = AuditRow(decision_id, shift, pnl, None, "inprocess", started, _now(), error=err)
        rows.append(row)
        if on_progress:
            on_progress(row)
    return fill_deltas(rows)


# -------------------------------------------------------------------------------------------------
# Fork mode: Tiger fork(s) taken at click time, one worker per shift. Default layout is one shared fork
# (free tier: 2 services per project); 'per_shift' gives every shift its own fork.
# -------------------------------------------------------------------------------------------------

SHIFT_STATES = ("queued", "forking", "ready", "replaying", "done", "failed")


@dataclass
class AuditEvent:
    elapsed_s: float
    shift: int | None
    state: str
    message: str


@dataclass
class AuditProgress:
    """Thread-safe progress log the dashboard polls while an audit runs in a background thread."""

    started: float = field(default_factory=time.monotonic)
    events: list[AuditEvent] = field(default_factory=list)
    states: dict[int, str] = field(default_factory=lambda: {s: "queued" for s in SHIFTS})
    workers: dict[int, str] = field(default_factory=dict)
    finished: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def emit(self, shift: int | None, state: str, message: str) -> None:
        with self._lock:
            if shift is not None and state in SHIFT_STATES:
                self.states[shift] = state
            self.events.append(AuditEvent(time.monotonic() - self.started, shift, state, message))

    def snapshot(self) -> tuple[dict[int, str], list[AuditEvent]]:
        with self._lock:
            return dict(self.states), list(self.events)

    def log_lines(self) -> list[str]:
        return [f"{e.elapsed_s:6.1f}s  {e.message}" for e in self.snapshot()[1]]


def wait_connectable(dsn: str, timeout: float = 60.0, interval: float = 2.0) -> None:
    """A Tiger fork can report READY a moment before it accepts connections."""
    import psycopg

    deadline = time.monotonic() + timeout
    while True:
        try:
            psycopg.connect(dsn, connect_timeout=5).close()
            return
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() + interval > deadline:
                raise TimeoutError(f"fork not connectable within {timeout:.0f}s: {exc}") from exc
            time.sleep(interval)


FORK_LAYOUTS = ("shared", "per_shift")


async def run_fork_async(
    decision_id: int,
    *,
    tiger,
    pool,
    parent_service_id: str,
    forks: str = "shared",
    shift_timeout: float = 180.0,
    fork_strategy: str = "NOW",
    connect_timeout: float = 60.0,
    progress: AuditProgress | None = None,
    connectable: Callable[[str, float], None] = wait_connectable,
) -> list[AuditRow]:
    """Fork the parent at click time, replay the five shifts on workers against the fork(s), and delete
    every fork afterwards whatever happened. Never raises for a single shift's failure.

    forks='per_shift': one fork per shift (needs 5 spare services on the Tiger project).
    forks='shared': one fork for the whole audit; the five workers replay into it concurrently under their
    own run_ids. Same isolation from live, same numbers; it fits the free tier's 2-service limit.
    """
    if forks not in FORK_LAYOUTS:
        raise ValueError(f"forks must be one of {FORK_LAYOUTS}, got {forks!r}")
    progress = progress or AuditProgress()
    # Own executor, shut down without waiting: a thread stuck past its shift's timeout (each one has its
    # own bounded timeout) must not hold up the other results. asyncio.to_thread would, because
    # asyncio.run joins the default executor on exit.
    executor = ThreadPoolExecutor(max_workers=4 * len(SHIFTS), thread_name_prefix=f"audit-{decision_id}")
    loop = asyncio.get_running_loop()

    def bg(fn, *args, **kwargs):
        return loop.run_in_executor(executor, functools.partial(fn, *args, **kwargs))

    created: dict[str, object] = {}
    created_lock = threading.Lock()
    names = {s: audit_run_id(decision_id, s) for s in SHIFTS}
    shared_name = f"audit-{decision_id}-all"

    def fork_and_record(name: str):
        svc = tiger.fork(parent_service_id, name, fork_strategy=fork_strategy)
        with created_lock:  # recorded from inside the thread, so a timeout can't lose it
            created[name] = svc
        return svc

    async def provision(name: str):
        svc = await bg(fork_and_record, name)
        ready = await bg(tiger.wait_ready, svc, timeout=shift_timeout, interval=2)
        dsn = tiger.connection_url(ready)
        await bg(connectable, dsn, connect_timeout)
        return ready, dsn

    shared_task = None
    if forks == "shared":
        progress.emit(None, "forking", f"fork {shared_name} requested (Tiger, fork_strategy {fork_strategy})")
        for s in SHIFTS:
            progress.states[s] = "forking"
        shared_task = asyncio.ensure_future(provision(shared_name))

    async def one(shift: int) -> AuditRow:
        started = _now()
        svc = None
        worker = None
        try:
            async with asyncio.timeout(shift_timeout):
                if shared_task is not None:
                    svc, dsn = await asyncio.shield(shared_task)  # one shift timing out can't cancel it
                    progress.emit(
                        shift, "ready", f"{names[shift]} using fork {shared_name} ({svc.service_id})"
                    )
                else:
                    progress.emit(
                        shift,
                        "forking",
                        f"fork {names[shift]} requested (Tiger, fork_strategy {fork_strategy})",
                    )
                    svc, dsn = await provision(names[shift])
                    progress.emit(shift, "ready", f"{names[shift]} READY ({svc.service_id})")

                def assigned(slot) -> None:
                    nonlocal worker
                    worker = slot.worker_id
                    progress.workers[shift] = worker
                    where = f" ({slot.region})" if getattr(slot, "region", None) else ""
                    progress.emit(shift, "replaying", f"{names[shift]} dispatched to {worker}{where}")

                result = await pool.replay(dsn, decision_id, shift, names[shift], on_assigned=assigned)
            progress.emit(shift, "done", f"{result.worker_id} -> £{result.pnl_gbp:,.2f} (shift {shift:+d})")
            return AuditRow(
                decision_id,
                shift,
                result.pnl_gbp,
                None,
                "fork",
                started,
                _now(),
                fork_service_id=getattr(svc, "service_id", None),
                worker_id=result.worker_id,
            )
        except Exception as exc:  # noqa: BLE001 - includes TimeoutError from asyncio.timeout
            msg = (
                f"timed out after {shift_timeout:.0f}s"
                if isinstance(exc, TimeoutError)
                else f"{type(exc).__name__}: {exc}"
            )
            progress.emit(shift, "failed", f"{names[shift]} failed: {msg}")
            with created_lock:
                fork_id = getattr(svc, "service_id", None) or getattr(
                    created.get(shared_name if shared_task else names[shift]), "service_id", None
                )
            return AuditRow(
                decision_id,
                shift,
                None,
                None,
                "fork",
                started,
                _now(),
                fork_service_id=fork_id,
                worker_id=worker,
                error=msg,
            )

    try:
        rows = list(await asyncio.gather(*(one(s) for s in SHIFTS)))
        if shared_task is not None and not shared_task.done():
            shared_task.cancel()
    finally:
        try:
            await _cleanup(tiger, created, created_lock, decision_id, progress)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    done = sum(not r.failed for r in rows)
    progress.emit(None, "finished", f"{done}/{len(rows)} done, forks deleted")
    progress.finished = True
    return fill_deltas(rows)


async def _cleanup(tiger, created, created_lock, decision_id, progress) -> None:
    with created_lock:
        to_delete = {name: svc.service_id for name, svc in created.items()}

    async def delete(name: str | None, service_id: str) -> None:
        try:
            await asyncio.to_thread(tiger.delete, service_id)
            progress.emit(None, "cleanup", f"deleted fork {name or service_id}")
        except Exception as exc:  # noqa: BLE001 - keep deleting the others
            progress.emit(None, "cleanup", f"delete {service_id} failed: {exc}")

    await asyncio.gather(*(delete(n, sid) for n, sid in to_delete.items()))
    # Belt and braces: sweep by name in case a fork call completed after its shift timed out.
    try:
        leftovers = await asyncio.to_thread(tiger.list_services)
        prefix = f"audit-{decision_id}-"
        for svc in leftovers:
            if svc.name.startswith(prefix) and svc.service_id not in to_delete.values():
                await delete(None, svc.service_id)
                progress.emit(None, "cleanup", f"swept leftover fork {svc.name} ({svc.service_id})")
    except Exception as exc:  # noqa: BLE001
        progress.emit(None, "cleanup", f"leftover sweep failed: {exc}")


def run_fork(
    conn, decision_id: int, *, tiger=None, pool=None, parent_service_id: str | None = None, **kwargs
):
    """Sync entry point for fork mode. Defaults: TigerClient from .env, the Vultr pool (or local workers
    when Vultr is not configured), and TIGER_PRIMARY_SERVICE_ID as the parent."""
    from tempo.audit.pool import default_pool
    from tempo.config import settings
    from tempo.infra.tiger import TigerClient

    progress = kwargs.setdefault("progress", AuditProgress())
    kwargs.setdefault("forks", settings().audit_forks)
    if pool is None:
        pool, note = default_pool()
        progress.emit(None, "info", note)
    tiger = tiger or TigerClient.from_env()
    parent_service_id = parent_service_id or settings().tiger.primary_service_id
    if not parent_service_id:
        raise ValueError("no parent service: set TIGER_PRIMARY_SERVICE_ID or pass parent_service_id")
    return asyncio.run(
        run_fork_async(decision_id, tiger=tiger, pool=pool, parent_service_id=parent_service_id, **kwargs)
    )


def run_audit(
    conn,
    decision_id: int,
    mode: str = "inprocess",
    *,
    write: bool = True,
    **kwargs,
) -> list[AuditRow]:
    """Run the five-shift timing audit for `decision_id` and write one `audits` row per shift.

    mode='inprocess': replay_shift on `conn` five times. mode='fork': Tiger fork(s) of the primary taken at
    call time, one worker per shift (kwargs: tiger, pool, parent_service_id, forks, shift_timeout, progress;
    `forks` defaults to TEMPO_AUDIT_FORKS). Rows go to `conn` either way; forks only hold battery_state.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    rows = (
        run_fork(conn, decision_id, **kwargs)
        if mode == "fork"
        else run_inprocess(conn, decision_id, **kwargs)
    )
    return write_audit_rows(conn, rows) if write else rows


def check_audit_rows(rows: list[AuditRow]) -> None:
    """Contract (plan.md section 5): five shifts -2..2, one each, same decision and mode, shift 0 delta 0,
    deltas consistent with pnl, finished_at >= started_at. Raises AssertionError with the reason."""
    assert sorted(r.shift for r in rows) == list(SHIFTS), f"shifts {sorted(r.shift for r in rows)}"
    assert len({r.decision_id for r in rows}) == 1, "rows span several decisions"
    assert len({r.mode for r in rows}) == 1 and rows[0].mode in MODES, "mixed or unknown mode"
    zero = next(r for r in rows if r.shift == 0)
    for r in rows:
        assert r.finished_at >= r.started_at, f"shift {r.shift} finished before it started"
        if r.pnl_gbp is None or zero.pnl_gbp is None:
            assert r.pnl_delta_gbp is None, f"shift {r.shift} has a delta without both pnls"
        else:
            assert abs(r.pnl_delta_gbp - (r.pnl_gbp - zero.pnl_gbp)) < 1e-9, f"shift {r.shift} delta wrong"
    if zero.pnl_gbp is not None:
        assert zero.pnl_delta_gbp == 0.0, "shift 0 delta must be exactly 0"
