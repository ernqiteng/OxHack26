"""Real Tiger fork: create, wait READY, connect with initial_password, SELECT 1, delete. Needs TEMPO_LIVE=1
and Tiger credentials plus TIGER_PRIMARY_SERVICE_ID in .env. Costs a free-tier fork for a minute or two."""

import time

import pytest

from tempo.config import settings
from tempo.infra.tiger import TigerClient

pytestmark = pytest.mark.live


def test_fork_roundtrip():
    psycopg = pytest.importorskip("psycopg")
    s = settings()
    if not s.tiger.configured or not s.tiger.primary_service_id:
        pytest.skip("Tiger credentials or TIGER_PRIMARY_SERVICE_ID missing")

    tiger = TigerClient.from_env()
    name = f"audit-live-test-{int(time.time())}"
    forked = None
    try:
        t0 = time.monotonic()
        forked = tiger.fork(s.tiger.primary_service_id, name)
        ready = tiger.wait_ready(forked, timeout=300, interval=5)
        t_ready = time.monotonic() - t0
        assert ready.ready
        assert ready.initial_password, "fork response should carry initial_password"

        dsn = tiger.connection_url(ready)
        deadline = time.monotonic() + 120
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(dsn, connect_timeout=10) as conn, conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    assert cur.fetchone() == (1,)
                break
            except Exception as exc:  # noqa: BLE001 - endpoint can lag READY by a few seconds
                last_exc = exc
                time.sleep(3)
        else:
            raise AssertionError(f"could not connect to fork after READY: {last_exc}")
        print(f"\nfork READY in {t_ready:.0f}s, connectable in {time.monotonic() - t0:.0f}s")
    finally:
        if forked is not None:
            tiger.delete(forked.service_id)
        tiger.close()
