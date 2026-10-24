"""run_audit(conn, decision_id, mode='inprocess'|'fork'): five shifts, forks, workers, audits rows, cleanup.

Owner: Ayo. See docs/ayo.md Phase 1 task 2 (in-process) and Phase 2 task 4 (fork).

One shift failing never sinks the audit: its row is written with pnl_gbp NULL and `error` set on the
returned AuditRow, and the other shifts still render. pnl_delta_gbp = pnl[shift] - pnl[0]; if shift 0
itself failed, every delta is NULL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


def run_audit(
    conn,
    decision_id: int,
    mode: str = "inprocess",
    *,
    write: bool = True,
    **kwargs,
) -> list[AuditRow]:
    """Run the five-shift timing audit for `decision_id` and write one `audits` row per shift."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if mode == "fork":
        raise NotImplementedError("fork mode lands in Phase 2 (docs/ayo.md)")
    rows = run_inprocess(conn, decision_id, **kwargs)
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
