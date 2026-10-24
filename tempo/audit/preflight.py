"""Pre-demo go/no-go checks behind scripts/demo_reset.py.

Owner: Ayo. See docs/ayo.md Phase 3 task 1 and description.md section 11.

Every check returns a `Check` with a level:
- FAIL: the on-stage fork audit would not work as planned. Any FAIL means NO-GO.
- WARN: it will work, but not the way the pitch says (e.g. local workers instead of Vultr) or something
  looks stale. Read them out loud at rehearsal.
- OK.

Checks, in order: Tiger primary state, stale `audit-*` forks (deleted unless dry_run), free service slots
for the audit's fork (the free tier holds 2 services), database reachable, prices fresh, worker health and
simulator agreement, and a decision worth clicking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

OK, WARN, FAIL = "OK", "WARN", "FAIL"
FREE_SERVICE_LIMIT = 2
FORKS_NEEDED = {"shared": 1, "per_shift": 5}
STALE_PRICE_AGE = timedelta(hours=3)


@dataclass
class Check:
    level: str
    name: str
    message: str


@dataclass
class Candidate:
    decision_id: int
    decided_at: datetime
    target_time: datetime
    action: str
    pnl: dict[int, float | None]
    has_hold: bool

    @property
    def zero_is_best(self) -> bool:
        base = self.pnl.get(0)
        return base is not None and all(v is None or v <= base + 1e-9 for v in self.pnl.values())

    @property
    def later_delta(self) -> float | None:
        if self.pnl.get(1) is None or self.pnl.get(0) is None:
            return None
        return self.pnl[1] - self.pnl[0]

    def sentence(self) -> str:
        d = self.later_delta
        if d is None:
            return "shift +1 could not be replayed"
        doing = {"charge": "Charging", "discharge": "Selling"}.get(self.action, "Acting")
        return f"{doing} one period later would have {'cost' if d < 0 else 'earned'} £{abs(d):,.2f}"


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    decision: Candidate | None = None
    candidates: list[Candidate] = field(default_factory=list)

    def add(self, level: str, name: str, message: str) -> None:
        self.checks.append(Check(level, name, message))

    @property
    def go(self) -> bool:
        return not any(c.level == FAIL for c in self.checks)

    def lines(self) -> list[str]:
        out = [f"[{c.level:>4}] {c.name:<10} {c.message}" for c in self.checks]
        if self.candidates:
            out.append("")
            out.append("Decisions worth clicking (best first):")
            for c in self.candidates[:5]:
                flags = ("as decided is best" if c.zero_is_best else "a shift beats it") + (
                    ", hold nearby" if c.has_hold else ""
                )
                out.append(
                    f"  #{c.decision_id:<6} {c.target_time:%a %d %b %H:%M} UTC  {c.action:<9} "
                    f"{c.sentence()}  ({flags})"
                )
        out.append("")
        if self.go:
            pick = f", click decision #{self.decision.decision_id}" if self.decision else ""
            warns = sum(c.level == WARN for c in self.checks)
            out.append(f"GO{pick}" + (f"  ({warns} warning{'s' * (warns != 1)}, read them)" if warns else ""))
        else:
            fails = [c.name for c in self.checks if c.level == FAIL]
            out.append(f"NO-GO: fix {', '.join(fails)}. In-process mode on the toggle still works.")
        return out


# -------------------------------------------------------------------------------------------------
# Tiger
# -------------------------------------------------------------------------------------------------


def check_tiger(report: Report, tiger, primary_id: str, *, forks: str, dry_run: bool, limit: int) -> None:
    try:
        services = tiger.list_services()
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "tiger", f"cannot list services: {exc}")
        return
    primary = next((s for s in services if s.service_id == primary_id), None)
    if primary is None:
        report.add(FAIL, "tiger", f"primary {primary_id} not found in the project")
        return
    if primary.status == "READY":
        report.add(OK, "tiger", f"primary {primary.name} ({primary_id}) READY")
    elif primary.status == "PAUSED":
        report.add(
            WARN, "tiger", f"primary {primary.name} is PAUSED; forks work, but resume it before the demo"
        )
    else:
        report.add(FAIL, "tiger", f"primary {primary.name} is {primary.status}, forks need READY")

    stale = [s for s in services if s.name.startswith("audit-") and s.service_id != primary_id]
    if stale and dry_run:
        report.add(
            FAIL, "forks", f"{len(stale)} stale audit fork(s): {', '.join(s.name for s in stale)} (dry run)"
        )
    elif stale:
        failed = []
        for s in stale:
            try:
                tiger.delete(s.service_id)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{s.name}: {exc}")
        if failed:
            report.add(FAIL, "forks", f"could not delete stale forks: {'; '.join(failed)}")
        else:
            report.add(
                OK, "forks", f"deleted {len(stale)} stale audit fork(s): {', '.join(s.name for s in stale)}"
            )
        services = [s for s in services if s not in stale]
    else:
        report.add(OK, "forks", "no stale audit forks")

    others = [s for s in services if s.service_id != primary_id]
    free = limit - 1 - len(others)
    need = FORKS_NEEDED[forks]
    if free >= need:
        report.add(OK, "slots", f"{free} free service slot(s) for the audit ({forks} layout needs {need})")
    else:
        who = f"; held by {', '.join(f'{s.name} ({s.status})' for s in others)}" if others else ""
        report.add(
            FAIL,
            "slots",
            f"{max(free, 0)} free service slot(s), {forks} layout needs {need} (limit {limit}){who}",
        )


def fork_test(report: Report, tiger, primary_id: str, timeout: float = 180) -> None:
    """Optional: take and delete one real fork, and time it. Uses the audit's slot for ~40 s."""
    import time

    svc = None
    t0 = time.monotonic()
    try:
        svc = tiger.fork(primary_id, f"preflight-{int(time.time())}")
        tiger.wait_ready(svc, timeout=timeout, interval=2)
        report.add(OK, "fork-test", f"real fork READY in {time.monotonic() - t0:.0f}s")
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "fork-test", f"real fork failed after {time.monotonic() - t0:.0f}s: {exc}")
    finally:
        if svc is not None:
            try:
                tiger.delete(svc.service_id)
            except Exception as exc:  # noqa: BLE001
                report.add(FAIL, "fork-test", f"could not delete test fork {svc.service_id}: {exc}")


# -------------------------------------------------------------------------------------------------
# Database and decision
# -------------------------------------------------------------------------------------------------


def check_database(report: Report, conn, now: datetime) -> bool:
    try:
        conn.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "database", f"unreachable: {exc}")
        return False
    report.add(OK, "database", "reachable")
    try:
        n_selftest = conn.execute("SELECT count(*) FROM decisions WHERE run_id = 'selftest'").fetchone()[0]
    except Exception:  # noqa: BLE001
        n_selftest = 0
    if n_selftest:
        report.add(
            WARN,
            "rehearsal",
            f"{n_selftest} rehearsal decision rows (run_id selftest) still present; "
            "remove before the demo: scripts/seed_selftest.py --remove",
        )
    try:
        n, latest = conn.execute("SELECT count(*), max(bucket) FROM prices_hh").fetchone()
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "prices", f"prices_hh unreadable: {exc}")
        return True
    if not n:
        report.add(FAIL, "prices", "prices_hh is empty, so nothing can be replayed")
    elif now - latest > STALE_PRICE_AGE:
        report.add(
            WARN, "prices", f"{n:,} rows, latest {latest:%d %b %H:%M} UTC is {now - latest} old: poller down?"
        )
    else:
        report.add(OK, "prices", f"{n:,} rows, latest {latest:%d %b %H:%M} UTC")
    return True


def find_candidates(conn, *, limit_batches: int = 30, score: bool = True, replay=None) -> list[Candidate]:
    """Live decision batches whose 48 periods all have actual prices, one non-hold decision from each,
    scored by an in-process audit. Best first: as-decided wins, a hold nearby, the biggest +1 cost."""
    from tempo.audit.orchestrator import run_audit

    batches = conn.execute(
        "SELECT decided_at, min(target_time), max(target_time), count(*), bool_or(action = 'hold') "
        "FROM decisions WHERE run_id = 'live' GROUP BY decided_at ORDER BY decided_at DESC LIMIT %s",
        (limit_batches,),
    ).fetchall()
    out: list[Candidate] = []
    for decided_at, first, last, n, has_hold in batches:
        priced = conn.execute(
            "SELECT count(*) FROM prices_hh WHERE bucket >= %s AND bucket <= %s AND price IS NOT NULL",
            (first, last),
        ).fetchone()[0]
        if priced < n:
            continue
        row = conn.execute(
            "SELECT decision_id, target_time, action FROM decisions "
            "WHERE run_id = 'live' AND decided_at = %s AND action <> 'hold' ORDER BY target_time LIMIT 1",
            (decided_at,),
        ).fetchone()
        if row is None:
            continue
        did, target, action = row
        pnl: dict[int, float | None] = {}
        if score:
            kwargs = {"replay": replay} if replay else {}
            for r in run_audit(conn, did, mode="inprocess", write=False, **kwargs):
                pnl[r.shift] = r.pnl_gbp
        out.append(Candidate(did, decided_at, target, action, pnl, bool(has_hold)))

    def rank(c: Candidate):
        d = c.later_delta
        return (not c.zero_is_best, not c.has_hold, d if d is not None else 0.0)

    return sorted(out, key=rank)


def check_decision(report: Report, conn, decision_id: int | None, *, score: bool = True, replay=None) -> None:
    try:
        cands = find_candidates(conn, score=score, replay=replay)
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "decision", f"could not read decisions: {exc}")
        return
    report.candidates = cands
    if decision_id is not None:
        chosen = next((c for c in cands if c.decision_id == decision_id), None)
        if chosen is None:
            report.add(
                FAIL, "decision", f"#{decision_id} is not a replayable live decision (missing prices?)"
            )
            return
    elif not cands:
        report.add(
            FAIL, "decision", "no replayable live decisions yet (needs Ernqi's run_decision and prices)"
        )
        return
    else:
        chosen = cands[0]
    report.decision = chosen
    level = OK if (chosen.zero_is_best or not score) else WARN
    note = "" if level == OK else " (a shifted timeline beats it; say so plainly on stage)"
    report.add(level, "decision", f"#{chosen.decision_id} {chosen.action}: {chosen.sentence()}{note}")


# -------------------------------------------------------------------------------------------------
# Workers
# -------------------------------------------------------------------------------------------------


def check_workers(report: Report, pool, *, expected: int = 5) -> None:
    from tempo.audit.refsim import resolve_sim

    if pool is None:
        report.add(FAIL, "workers", "no worker pool")
        return
    try:
        health = asyncio.run(pool.health())
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "workers", f"health check crashed: {exc}")
        return
    bad = {w: detail for w, (ok, detail) in health.items() if not ok}
    if bad:
        report.add(FAIL, "workers", "unhealthy: " + "; ".join(f"{w}: {d[:80]}" for w, d in bad.items()))
        return
    kind = getattr(pool, "kind", "http")
    names = ", ".join(sorted(health))
    if kind == "local":
        report.add(
            WARN, "workers", f"{len(health)} local workers ({names}): Vultr not configured, don't say Vultr"
        )
    elif len(health) < expected:
        report.add(
            WARN, "workers", f"only {len(health)}/{expected} Vultr workers healthy ({names}); timelines queue"
        )
    else:
        report.add(OK, "workers", f"{len(health)} Vultr workers healthy ({names})")

    import json

    sims = set()
    for _, detail in health.values():
        try:
            sims.add(json.loads(detail).get("simulator"))
        except (ValueError, AttributeError):
            pass
    local_sim = resolve_sim()[1]
    if sims and sims != {local_sim}:
        report.add(
            WARN,
            "simulator",
            f"workers run {', '.join(map(str, sims))}, this machine runs {local_sim}: rebuild image",
        )


# -------------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------------


def run_preflight(
    *,
    tiger,
    pool,
    conn,
    primary_id: str,
    forks: str = "shared",
    dry_run: bool = False,
    decision_id: int | None = None,
    score: bool = True,
    with_fork_test: bool = False,
    limit: int = FREE_SERVICE_LIMIT,
    now: datetime | None = None,
    replay=None,
) -> Report:
    report = Report()
    if forks not in FORKS_NEEDED:
        report.add(FAIL, "config", f"TEMPO_AUDIT_FORKS={forks!r}, expected shared or per_shift")
        return report
    report.add(OK, "config", f"fork layout {forks}")
    check_tiger(report, tiger, primary_id, forks=forks, dry_run=dry_run, limit=limit)
    if with_fork_test and report.go:
        fork_test(report, tiger, primary_id)
    if conn is None:
        report.add(FAIL, "database", "no connection (TEMPO_DATABASE_URL missing or unreachable)")
    elif check_database(report, conn, now or datetime.now(tz=UTC)):
        check_decision(report, conn, decision_id, score=score, replay=replay)
    check_workers(report, pool)
    return report
