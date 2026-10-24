"""Pre-demo go/no-go (docs/ayo.md Phase 3): no-go when a worker is unhealthy, a stale fork is left or a
slot is taken; go when clean. Fake Tiger, fake pool, stub DB; no network."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from tempo.audit.preflight import FAIL, OK, WARN, run_preflight
from tempo.audit.refsim import resolve_sim
from tempo.infra.tiger import Service

LOCAL_SIM = resolve_sim()[1]

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
PRIMARY = "prim"


class FakeTiger:
    def __init__(self, services, fail_delete=False):
        self.services = list(services)
        self.deleted = []
        self.fail_delete = fail_delete

    def list_services(self):
        return list(self.services)

    def delete(self, sid):
        if self.fail_delete:
            raise RuntimeError("503")
        self.deleted.append(sid)
        self.services = [s for s in self.services if s.service_id != sid]


class FakePool:
    def __init__(self, health, kind="http"):
        self._health, self.kind = health, kind

    async def health(self):
        return self._health


def healthy(n=5, sim=LOCAL_SIM, prefix="tempo-worker"):
    body = json.dumps({"ok": True, "simulator": sim})
    return {f"{prefix}-{k}": (True, body) for k in range(1, n + 1)}


class StubConn:
    """Answers the handful of queries preflight makes."""

    def __init__(
        self, prices=(17_000, NOW - timedelta(minutes=40)), decisions=True, broken=False, selftest_rows=0
    ):
        self.prices, self.decisions, self.broken = prices, decisions, broken
        self.selftest_rows = selftest_rows

    def execute(self, sql, params=()):
        if self.broken:
            raise RuntimeError("connection refused")
        rows = [(1,)]
        if "run_id = 'selftest'" in sql:
            rows = [(self.selftest_rows,)]
        elif "FROM prices_hh" in sql and "count(*), max(bucket)" in sql:
            rows = [self.prices]
        elif "GROUP BY decided_at" in sql:
            t = NOW - timedelta(days=1)
            rows = (
                [(t, t + timedelta(minutes=30), t + timedelta(hours=24), 48, True)] if self.decisions else []
            )
        elif "FROM prices_hh" in sql:
            rows = [(48,)]
        elif "action <> 'hold'" in sql:
            rows = [(101, NOW - timedelta(hours=20), "charge")]
        return Rows(rows)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def svc(sid, name, status="READY"):
    return Service(service_id=sid, name=name, status=status)


def run(tiger=None, pool=None, conn=None, **kw):
    kw.setdefault("score", False)
    return run_preflight(
        tiger=tiger or FakeTiger([svc(PRIMARY, "db-40426")]),
        pool=pool or FakePool(healthy()),
        conn=conn if conn is not None else StubConn(),
        primary_id=PRIMARY,
        now=NOW,
        **kw,
    )


def levels(report):
    return {c.name: c.level for c in report.checks}


def test_go_when_clean():
    r = run()
    assert r.go, r.lines()
    assert set(levels(r).values()) == {OK}
    assert r.decision.decision_id == 101
    assert r.lines()[-1] == "GO (decisions not scored: run without --no-score to choose one)"


def test_unhealthy_worker_is_no_go():
    h = healthy()
    h["tempo-worker-3"] = (False, "ConnectError: refused")
    r = run(pool=FakePool(h))
    assert not r.go and levels(r)["workers"] == FAIL
    assert "tempo-worker-3" in next(c.message for c in r.checks if c.name == "workers")
    assert r.lines()[-1].startswith("NO-GO: fix workers")


def test_stale_fork_is_deleted_then_go():
    tiger = FakeTiger([svc(PRIMARY, "db-40426"), svc("f1", "audit-12-all")])
    r = run(tiger=tiger)
    assert tiger.deleted == ["f1"]
    assert r.go and levels(r)["forks"] == OK and levels(r)["slots"] == OK


def test_stale_fork_in_dry_run_is_no_go():
    tiger = FakeTiger([svc(PRIMARY, "db-40426"), svc("f1", "audit-12-all")])
    r = run(tiger=tiger, dry_run=True)
    assert tiger.deleted == [] and not r.go and levels(r)["forks"] == FAIL


def test_stale_fork_that_wont_delete_is_no_go():
    tiger = FakeTiger([svc(PRIMARY, "db-40426"), svc("f1", "audit-12-all")], fail_delete=True)
    assert levels(run(tiger=tiger))["forks"] == FAIL


def test_someone_elses_service_holding_the_slot_is_no_go():
    tiger = FakeTiger([svc(PRIMARY, "db-40426"), svc("g1", "girik-scratch")])
    r = run(tiger=tiger)
    assert tiger.deleted == []  # never touches non-audit services
    assert not r.go and levels(r)["slots"] == FAIL
    assert "girik-scratch" in next(c.message for c in r.checks if c.name == "slots")


def test_per_shift_layout_needs_five_slots():
    r = run(forks="per_shift")
    assert levels(r)["slots"] == FAIL
    assert run(forks="per_shift", limit=6).go


def test_primary_not_ready_is_no_go_and_paused_is_warn():
    assert levels(run(tiger=FakeTiger([svc(PRIMARY, "db", "CONFIGURING")])))["tiger"] == FAIL
    r = run(tiger=FakeTiger([svc(PRIMARY, "db", "PAUSED")]))
    assert levels(r)["tiger"] == WARN and r.go


def test_missing_primary_is_no_go():
    assert levels(run(tiger=FakeTiger([svc("other", "db")])))["tiger"] == FAIL


def test_local_workers_warn_but_go():
    r = run(pool=FakePool(healthy(prefix="local"), kind="local"))
    assert r.go and levels(r)["workers"] == WARN
    assert "don't say Vultr" in next(c.message for c in r.checks if c.name == "workers")


def test_too_few_vultr_workers_warn():
    r = run(pool=FakePool(healthy(3)))
    assert r.go and levels(r)["workers"] == WARN


def test_simulator_mismatch_warns():
    r = run(pool=FakePool(healthy(sim="some-other-simulator")))
    assert levels(r)["simulator"] == WARN


def test_database_down_is_no_go():
    r = run(conn=StubConn(broken=True))
    assert not r.go and levels(r)["database"] == FAIL


def test_empty_prices_is_no_go_and_stale_prices_warn():
    assert levels(run(conn=StubConn(prices=(0, None))))["prices"] == FAIL
    r = run(conn=StubConn(prices=(100, NOW - timedelta(hours=8))))
    assert levels(r)["prices"] == WARN and r.go


def test_no_live_decisions_is_no_go():
    r = run(conn=StubConn(decisions=False))
    assert not r.go and levels(r)["decision"] == FAIL


def test_requested_decision_must_be_replayable():
    assert levels(run(decision_id=999))["decision"] == FAIL
    assert run(decision_id=101).decision.decision_id == 101


def test_no_pool_is_no_go():
    r = run_preflight(
        tiger=FakeTiger([svc(PRIMARY, "db")]),
        pool=None,
        conn=StubConn(),
        primary_id=PRIMARY,
        now=NOW,
        score=False,
    )
    assert levels(r)["workers"] == FAIL


@pytest.mark.parametrize("forks", ["many", ""])
def test_bad_layout_is_no_go(forks):
    assert not run(forks=forks).go


def test_rehearsal_rows_warn_but_go():
    r = run(conn=StubConn(selftest_rows=48))
    assert r.go and levels(r)["rehearsal"] == WARN
    assert "seed_selftest.py --remove" in next(c.message for c in r.checks if c.name == "rehearsal")


def test_unscored_candidates_say_so():
    r = run(score=False)
    assert r.decision.decision_id == 101
    assert "not scored" in r.decision.sentence()
    assert "could not be replayed" not in "\n".join(r.lines())
