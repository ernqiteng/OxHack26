"""The key Phase 2 test (docs/ayo.md): replaying in forks through the worker's HTTP code path gives the
same PnL as the in-process audit, to the penny, for all five shifts. No cloud.

"Forks" are real copies of a source database made with CREATE DATABASE ... TEMPLATE on the local Docker
TimescaleDB, created and dropped through a TigerClient-shaped fake. Workers are the real FastAPI worker app
served in-process (LocalWorkerPool). Each fork gets its own connection string, exactly as on Tiger.
"""

import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import numpy as np
import psycopg
import pytest

from tempo.audit.orchestrator import AuditProgress, check_audit_rows, run_audit
from tempo.audit.pool import LocalWorkerPool
from tempo.infra.tiger import Service

from .conftest import T0, day_prices, targets

SCHEMA = (Path(__file__).resolve().parents[2] / "tempo/db/schema.sql").read_text()
BASE_URL = os.environ.get("TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres")
SRC = "tempo_fork_src"


def url_for(db: str) -> str:
    u = urlparse(BASE_URL)
    return urlunparse(u._replace(path=f"/{db}"))


def drop(admin, db: str) -> None:
    admin.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')


class TemplateTiger:
    """TigerClient-shaped: fork = CREATE DATABASE <name> TEMPLATE <parent>, delete = DROP DATABASE."""

    def __init__(self, admin):
        self.admin = admin
        self.lock = threading.Lock()  # template copies of one source cannot run concurrently in Postgres
        self.live: dict[str, str] = {}

    def fork(self, parent, name, fork_strategy="NOW"):
        db = "f_" + name.replace("-", "_")
        with self.lock:
            for _ in range(20):
                try:
                    self.admin.execute(f'CREATE DATABASE "{db}" TEMPLATE "{parent}"')
                    break
                except psycopg.errors.ObjectInUse:
                    # TimescaleDB's background worker can briefly hold the source; kick it and retry.
                    self.admin.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (parent,)
                    )
                    time.sleep(0.2)
            else:
                raise RuntimeError(f"could not copy {parent}")
            self.live[db] = name
        return Service(service_id=db, name=name, status="QUEUED", host="localhost", port=5433)

    def wait_ready(self, svc, timeout=180, interval=2):
        return Service(svc.service_id, svc.name, "READY", svc.host, svc.port)

    @staticmethod
    def connection_url(svc):
        return url_for(svc.service_id)

    def delete(self, service_id):
        with self.lock:
            drop(self.admin, service_id)
            self.live.pop(service_id, None)

    def list_services(self):
        return [Service(db, name, "READY") for db, name in self.live.items()]


@pytest.fixture
def source_db(db_conn):
    """A fresh database with the real schema, a plain prices_hh table, one decision batch and a start SoC."""
    admin = db_conn
    drop(admin, SRC)
    admin.execute(f'CREATE DATABASE "{SRC}"')
    rng = np.random.default_rng(7)
    mw = rng.choice([-1.0, 0.0, 0.0, 1.0], size=48)
    with psycopg.connect(url_for(SRC), autocommit=True) as src:
        src.execute(SCHEMA)
        src.execute(
            "CREATE TABLE IF NOT EXISTS prices_hh "
            "(bucket timestamptz PRIMARY KEY, price float8, volume float8)"
        )
        with src.cursor() as cur:
            cur.executemany(
                "INSERT INTO prices_hh VALUES (%s, %s, 100)",
                [(t, float(p)) for t, p in zip(targets(), day_prices(3), strict=True)],
            )
            ids = []
            for t, m in zip(targets(), mw, strict=True):
                action = "charge" if m > 0 else "discharge" if m < 0 else "hold"
                cur.execute(
                    "INSERT INTO decisions (decided_at, target_time, action, mw, reason) "
                    "VALUES (%s, %s, %s, %s, 'test') RETURNING decision_id",
                    (T0, t, action, float(m)),
                )
                ids.append(cur.fetchone()[0])
            cur.execute("INSERT INTO battery_state VALUES (%s, 0.7, 0, 'live')", (T0,))
    yield admin, ids[0]
    drop(admin, SRC)
    for (db,) in admin.execute("SELECT datname FROM pg_database WHERE datname LIKE 'f_audit_%'").fetchall():
        drop(admin, db)


@pytest.mark.parametrize("forks", ["per_shift", "shared"])
def test_fork_replay_equals_inprocess_to_the_penny(source_db, forks):
    admin, did = source_db
    tiger = TemplateTiger(admin)
    progress = AuditProgress()

    # Fork first, while nothing is connected to the source (Postgres requires that for TEMPLATE copies).
    fork_rows = run_audit(
        None,
        did,
        mode="fork",
        write=False,
        tiger=tiger,
        pool=LocalWorkerPool(5),
        parent_service_id=SRC,
        progress=progress,
        forks=forks,
    )

    with psycopg.connect(url_for(SRC), autocommit=True) as src:
        leaked = src.execute("SELECT count(*) FROM battery_state WHERE run_id LIKE 'audit-%'").fetchone()[0]
        assert leaked == 0, "fork replays must write to their forks, not the source"
        inproc_rows = run_audit(src, did, mode="inprocess")

    check_audit_rows(fork_rows)
    check_audit_rows(inproc_rows)
    assert [r.error for r in fork_rows] == [None] * 5, progress.log_lines()
    for f, i in zip(fork_rows, inproc_rows, strict=True):
        assert f.shift == i.shift
        assert round(f.pnl_gbp, 2) == round(i.pnl_gbp, 2), f"shift {f.shift}: fork {f.pnl_gbp} vs {i.pnl_gbp}"
        assert f.pnl_gbp == pytest.approx(i.pnl_gbp, abs=1e-9)
    assert {r.worker_id for r in fork_rows} <= {f"local-{k}" for k in range(1, 6)}
    assert all(r.fork_service_id.startswith("f_audit_") for r in fork_rows)
    assert len({r.fork_service_id for r in fork_rows}) == (1 if forks == "shared" else 5)
    assert tiger.live == {}, "every fork database must be dropped"
    left = admin.execute("SELECT count(*) FROM pg_database WHERE datname LIKE 'f_audit_%'").fetchone()[0]
    assert left == 0


def test_worker_replay_writes_into_its_fork(source_db):
    """Run the worker against one copy directly and check the rows landed there and only there."""
    from fastapi.testclient import TestClient

    from tempo.worker.main import app

    admin, did = source_db
    tiger = TemplateTiger(admin)
    svc = tiger.fork(SRC, f"audit-{did}-1")
    try:
        r = TestClient(app).post(
            "/replay",
            json={
                "database_url": tiger.connection_url(svc),
                "decision_id": did,
                "shift": 1,
                "run_id": f"audit-{did}-1",
            },
        )
        assert r.status_code == 200, r.text
        with psycopg.connect(tiger.connection_url(svc)) as fork:
            n = fork.execute(
                "SELECT count(*) FROM battery_state WHERE run_id = %s", (f"audit-{did}-1",)
            ).fetchone()[0]
        assert n == 48
        with psycopg.connect(url_for(SRC)) as src:
            assert (
                src.execute("SELECT count(*) FROM battery_state WHERE run_id LIKE 'audit-%'").fetchone()[0]
                == 0
            )
    finally:
        tiger.delete(svc.service_id)


def test_worker_returns_422_for_unknown_decision(source_db):
    from fastapi.testclient import TestClient

    from tempo.worker.main import app

    r = TestClient(app).post(
        "/replay", json={"database_url": url_for(SRC), "decision_id": 999_999, "shift": 0, "run_id": "x"}
    )
    assert r.status_code == 422 and "not found" in r.json()["detail"]
