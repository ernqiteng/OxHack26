"""Shared pytest configuration.

- `live` tests are skipped unless TEMPO_LIVE=1.
- `db_conn` fixture connects to the local Docker TimescaleDB (scripts/dev_db.sh) and
  truncates every table after each test so tests never see each other's rows.
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TEMPO_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="set TEMPO_LIVE=1 to run live tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def db_conn():
    psycopg = pytest.importorskip("psycopg")
    url = os.environ.get("TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres")
    try:
        conn = psycopg.connect(url, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local test DB not reachable ({exc}); run scripts/dev_db.sh")
    yield conn
    with conn.cursor() as cur:
        cur.execute("TRUNCATE grid_raw, forecasts, decisions, battery_state, audits, backtest_results")
    conn.close()
