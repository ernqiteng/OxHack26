"""Background audit jobs for the dashboard: run the fork audit in a thread, let the page poll progress.

Owner: Ayo. See docs/ayo.md Phase 2 task 5 and docs/ui.md section 5.3.

A Streamlit page cannot block for the ~40 s a fork takes, so `AuditJob` runs `run_audit(mode='fork')` in a
daemon thread with its own database connection (psycopg connections are not shared across threads) and
exposes `progress` (AuditProgress), `done`, `rows` and `error`. The page keeps the job in session_state and
re-renders a fragment every half second until `done`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from tempo.audit.orchestrator import SHIFTS, AuditProgress, AuditRow

STATE_LABEL = {
    "queued": "queued",
    "forking": "forking…",
    "ready": "fork ready",
    "replaying": "replaying",
    "done": "done",
    "failed": "failed",
}


def rows_frame(rows: list[AuditRow]) -> pd.DataFrame:
    return pd.DataFrame([{**r.__dict__} for r in rows])


class AuditJob:
    """One fork-mode audit running in the background."""

    def __init__(
        self,
        decision_id: int,
        *,
        conn_factory: Callable[[], object],
        runner: Callable[..., list[AuditRow]] | None = None,
        **audit_kwargs,
    ) -> None:
        self.decision_id = decision_id
        self.mode = "fork"
        self.progress = AuditProgress()
        self.rows: pd.DataFrame | None = None
        self.error: str | None = None
        self.started = time.monotonic()
        self.elapsed_s: float | None = None
        self._conn_factory = conn_factory
        self._runner = runner
        self._kwargs = audit_kwargs
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"audit-job-{decision_id}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        conn = None
        try:
            runner = self._runner
            if runner is None:
                from tempo.audit.orchestrator import run_audit

                runner = run_audit
            conn = self._conn_factory()
            rows = runner(conn, self.decision_id, mode="fork", progress=self.progress, **self._kwargs)
            self.rows = rows_frame(rows)
        except Exception as exc:  # noqa: BLE001 - surfaced on the page, never swallowed
            self.error = f"{type(exc).__name__}: {exc}"
            self.progress.emit(None, "failed", f"audit crashed: {self.error}")
        finally:
            self.elapsed_s = time.monotonic() - self.started
            self.progress.finished = True
            try:
                if conn is not None and hasattr(conn, "close"):
                    conn.close()
            finally:
                self._done.set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def running_s(self) -> float:
        return (self.elapsed_s if self.elapsed_s is not None else time.monotonic() - self.started) or 0.0

    def states(self) -> dict[int, str]:
        return self.progress.snapshot()[0]

    def log_lines(self, last: int = 14) -> list[str]:
        return self.progress.log_lines()[-last:]


@dataclass
class CompletedJob:
    """A job that is already finished: the synthetic source hands these out so the page logic is identical."""

    decision_id: int
    rows: pd.DataFrame
    mode: str = "fork"
    error: str | None = None
    elapsed_s: float = 0.0
    note: str | None = None
    progress: AuditProgress = field(default_factory=AuditProgress)
    done: bool = True

    @property
    def running_s(self) -> float:
        return self.elapsed_s

    def states(self) -> dict[int, str]:
        return {s: "done" for s in SHIFTS}

    def log_lines(self, last: int = 14) -> list[str]:
        return self.progress.log_lines()[-last:]


SHIFT_PHRASE = {-2: "an hour earlier", -1: "30 minutes earlier", 1: "30 minutes later", 2: "an hour later"}
ACTION_VERB = {"charge": "Charging", "discharge": "Selling", "hold": "Acting"}


def hero_sentence(rows: pd.DataFrame, action: str | None) -> str | None:
    """The one line the presenter reads (docs/ui.md 5.3). Names the worst of the four shifts; adds
    "Tempo picked the best of the five" only when shift 0 is the maximum. If a shift beats the real
    decision, says so plainly: honesty is the brand."""
    verb = ACTION_VERB.get(action or "", "Acting")
    deltas = {
        int(r.shift): float(r.pnl_delta_gbp)
        for r in rows.itertuples()
        if int(r.shift) != 0 and r.pnl_delta_gbp is not None and not pd.isna(r.pnl_delta_gbp)
    }
    if not deltas:
        return None
    best_shift, best = max(deltas.items(), key=lambda kv: kv[1])
    worst_shift, worst = min(deltas.items(), key=lambda kv: kv[1])
    if best > 0.005:
        return (
            f"{verb} {SHIFT_PHRASE[best_shift]} would have earned £{best:,.2f} more. Tempo mistimed this one."
        )
    if worst < -0.005:
        return (
            f"{verb} {SHIFT_PHRASE[worst_shift]} would have cost £{-worst:,.2f}. "
            "Tempo picked the best of the five."
        )
    return "Shifting this decision by up to an hour would have made no difference."
