"""The two-year price query behind the dashboard chart is instant (docs/girik.md Phase 3).

Runs on the FULL local backfill (scripts/backfill.py into the tempo_local database; override with
TEMPO_FULL_DATABASE_URL), not the empty test database, because the point is two years of real data.
Measured on Tiger as well; the number is recorded in docs/needs.md.
"""

import os
import statistics
import time

import pytest

TWO_YEAR_QUERY = "SELECT bucket, price FROM prices_hh ORDER BY bucket"  # verbatim from girik.md
FULL_URL = os.environ.get("TEMPO_FULL_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/tempo_local")


@pytest.fixture(scope="module")
def full_conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        conn = psycopg.connect(FULL_URL, autocommit=True)
        (n,) = conn.execute("SELECT count(*) FROM prices_hh").fetchone()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"full local backfill not reachable ({exc}); run scripts/backfill.py into tempo_local")
    if n < 34_000:
        pytest.skip(f"tempo_local has {n} prices_hh rows; needs the full 2-year backfill (~35k)")
    yield conn
    conn.close()


def timed_fetch(conn, sql):
    t0 = time.perf_counter()
    rows = conn.execute(sql).fetchall()
    return time.perf_counter() - t0, rows


@pytest.mark.slow
def test_two_year_query_returns_two_years(full_conn):
    _, rows = timed_fetch(full_conn, TWO_YEAR_QUERY)
    assert len(rows) >= 34_000
    assert (rows[-1][0] - rows[0][0]).days >= 700


@pytest.mark.slow
def test_two_year_query_under_one_second(full_conn):
    """Median of 3 runs after one warm-up, including fetching every row into Python."""
    timed_fetch(full_conn, TWO_YEAR_QUERY)
    runs = [timed_fetch(full_conn, TWO_YEAR_QUERY)[0] for _ in range(3)]
    assert statistics.median(runs) < 1.0, f"two-year query took {runs} s"


@pytest.mark.slow
def test_two_year_query_server_time_under_one_second(full_conn):
    plan = full_conn.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {TWO_YEAR_QUERY}").fetchone()[0]
    assert plan[0]["Execution Time"] < 1000, plan[0]["Execution Time"]
