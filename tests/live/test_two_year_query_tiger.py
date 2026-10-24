"""Two-year price query on the real Tiger service (opt-in: TEMPO_LIVE=1). Read-only.

Measured 24 Oct 2026 from a laptop ~280 ms from us-east-1: the half-hourly query EXECUTES in ~19 ms on
Tiger, but fetching its 35k rows takes 5 to 36 s over that link. So the server-side guarantee is pinned
here, and the two-year chart should draw from prices_daily (731 rows, ~0.65 s from the same laptop).
"""

import time

import pytest

from tempo.db.conn import get_conn

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def tiger():
    conn = get_conn()  # TEMPO_DATABASE_URL from .env
    yield conn
    conn.close()


def test_two_year_query_executes_under_one_second_on_tiger(tiger):
    plan = tiger.execute(
        "EXPLAIN (ANALYZE, FORMAT JSON) SELECT bucket, price FROM prices_hh ORDER BY bucket"
    ).fetchone()[0][0]
    assert plan["Execution Time"] < 1000, plan["Execution Time"]
    assert plan["Plan"]["Actual Rows"] >= 34_000


def test_two_year_daily_chart_fetches_under_two_seconds(tiger):
    tiger.execute("SELECT bucket, mean, min, max FROM prices_daily ORDER BY bucket").fetchall()  # warm-up
    t0 = time.perf_counter()
    rows = tiger.execute("SELECT bucket, mean, min, max FROM prices_daily ORDER BY bucket").fetchall()
    elapsed = time.perf_counter() - t0
    assert len(rows) >= 700
    assert elapsed < 2.0, f"{elapsed:.2f} s to fetch {len(rows)} daily rows"
