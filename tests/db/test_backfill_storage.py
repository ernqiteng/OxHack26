"""Storage safety for the Tiger free service (750 MB, read-only at the cap).

Found on the first Tiger run: chunks were compressed only after a whole dataset, so the remaining NDF
windows (~1.4M rows) would have piled up uncompressed; and the guard read pg_database_size, which misses
Tiger's ~340 MB overhead. These tests pin the fixes: compress after every window, check the guard before
every window, and read the guard from an injectable storage function (tiger_storage_mb against Tiger).
"""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from tempo.db.conn import apply_schema, run_sql
from tempo.db.stats import tiger_storage_mb
from tempo.ingest.backfill import StorageLimitExceeded, backfill
from tests.db.helpers import clean
from tests.db.test_backfill_idempotent import SynthClient

START = datetime(2025, 10, 21, tzinfo=UTC)
END = datetime(2025, 10, 25, tzinfo=UTC)  # 4 one-day windows, all in chunks older than 7 days


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    try:
        yield db_conn
    finally:
        clean(db_conn, START, END)


def logged_windows(conn, dataset="INDO"):
    return run_sql(conn, "SELECT count(*) FROM ingest_log WHERE dataset = %s", (dataset,))[0][0]


def uncompressed_rows(conn) -> int:
    """Rows sitting in chunk heaps (i.e. not in the columnstore), across EVERY grid_raw chunk.

    Not chunk_residue(): that only looks at chunks already marked compressed, and a fresh window lands in a
    brand-new uncompressed chunk, so a probe built on it passed even with compression moved to the end of
    the dataset (caught by the mutation check)."""
    chunks = run_sql(
        conn,
        "SELECT c.relid::text FROM _timescaledb_catalog.chunk c "
        "JOIN _timescaledb_catalog.hypertable h ON h.id = c.hypertable_id WHERE h.table_name = 'grid_raw'",
    )
    total = 0
    for (relid,) in chunks:
        schema, name = relid.split(".")
        total += run_sql(conn, f'SELECT count(*) FROM ONLY "{schema}"."{name}"')[0][0]  # noqa: S608
    return total


def test_every_window_is_compressed_before_the_next_one(conn):
    """The storage probe runs before each window; at that moment nothing from earlier windows may still be
    uncompressed in any chunk. The windows are in Oct 2025, so their chunks are older than the 7-day
    compression horizon and must be compressed straight away."""
    seen = []

    def probe():
        seen.append(uncompressed_rows(conn))
        return 0.0

    backfill(
        conn, SynthClient(), datasets=("INDO",), days=4, end=END, window_days=1,
        refresh=False, max_storage_mb=10_000, storage_fn=probe,
    )  # fmt: skip
    assert len(seen) == 4  # probed before each of the 4 windows
    assert seen == [0, 0, 0, 0]
    assert uncompressed_rows(conn) == 0  # and after the last window
    assert run_sql(conn, "SELECT count(*) FROM grid_raw WHERE dataset = 'INDO'")[0][0] == 4 * 48  # rows kept


def test_guard_stops_before_the_window_that_would_cross_the_limit(conn):
    """The limit is checked before every window, not once per dataset: storage reads 10, 20, 30 ... and the
    limit is 25, so exactly two windows load and the third is refused."""
    readings = iter([10.0, 20.0, 30.0, 40.0])
    with pytest.raises(StorageLimitExceeded, match="30 MB used > 25"):
        backfill(
            conn, SynthClient(), datasets=("INDO",), days=4, end=END, window_days=1,
            refresh=False, max_storage_mb=25, storage_fn=lambda: next(readings),
        )  # fmt: skip
    assert logged_windows(conn) == 2
    # Resume after the limit is raised picks up exactly where it stopped.
    client = SynthClient()
    backfill(conn, client, datasets=("INDO",), days=4, end=END, window_days=1, refresh=False)
    assert client.calls == 2 and logged_windows(conn) == 4


def test_storage_limit_aborts_before_loading_anything(conn):
    with pytest.raises(StorageLimitExceeded):
        backfill(
            conn, SynthClient(), datasets=("INDO",), days=4, end=END, window_days=1, max_storage_mb=0.001
        )
    assert logged_windows(conn) == 0


@respx.mock
def test_tiger_storage_mb_reads_the_service_metric():
    from tempo.infra.tiger import TigerClient

    route = respx.get("https://tiger.test/projects/p1/services/svc1").mock(
        return_value=httpx.Response(
            200, json={"service_id": "svc1", "status": "READY", "metrics": {"storage_mb": 533}}
        )
    )
    client = TigerClient("p1", "ak", "sk", base_url="https://tiger.test")
    assert tiger_storage_mb(client, "svc1") == 533.0
    assert route.calls[0].request.headers["authorization"].startswith("Basic ")


@respx.mock
def test_tiger_storage_mb_refuses_a_missing_metric():
    from tempo.infra.tiger import TigerClient

    respx.get("https://tiger.test/projects/p1/services/svc1").mock(
        return_value=httpx.Response(200, json={"service_id": "svc1", "status": "READY"})
    )
    with pytest.raises(RuntimeError, match="no metrics.storage_mb"):
        tiger_storage_mb(TigerClient("p1", "ak", "sk", base_url="https://tiger.test"), "svc1")
