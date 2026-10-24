"""backfill() twice on the same window leaves the row count unchanged; resume skips loaded windows."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tempo.db.conn import apply_schema, run_sql
from tempo.ingest.backfill import backfill
from tempo.ingest.elexon import _rows
from tests.db.helpers import clean

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "elexon_samples"
START = datetime(2025, 10, 25, tzinfo=UTC)
END = datetime(2025, 10, 27, tzinfo=UTC)


class FakeClient:
    """Replays the saved 2025-10-26 samples, filtered to the requested window. No network."""

    def __init__(self):
        self.calls = 0

    def fetch_window(self, dataset, start, end, bulk=True):
        self.calls += 1
        rows = _rows(json.loads((SAMPLES / f"{dataset}_2025-10-26.json").read_text(encoding="utf-8")))
        return [r for r in rows if start <= pd.Timestamp(r["startTime"]) < end]


class SynthClient:
    """Generates API-shaped rows every 30 min for any window, so multi-window resume can be tested.

    spill_hours > 0 imitates Elexon's real from/to behaviour: the response runs past `end` to the end of
    the settlement day, so each window leaks a few hours into the next one."""

    def __init__(self, spill_hours: float = 0):
        self.calls = 0
        self.windows: list[tuple] = []
        self.spill = pd.Timedelta(hours=spill_hours)

    def fetch_window(self, dataset, start, end, bulk=True):
        self.calls += 1
        self.windows.append((dataset, start, end))
        out = []
        for i, t in enumerate(pd.date_range(start, end + self.spill, freq="30min", inclusive="left", tz=UTC)):
            iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            common = {"startTime": iso, "settlementDate": iso[:10], "settlementPeriod": i % 48 + 1}
            if dataset == "MID":
                out.append({**common, "dataProvider": "APXMIDP", "price": 50.0 + i % 7, "volume": 100.0})
            elif dataset == "INDO":
                out.append({**common, "publishTime": iso, "initialDemandOutturn": 30000.0 + i})
            elif dataset == "DISEBSP":
                out.append({**common, "createdDateTime": iso, "systemSellPrice": 60.0 + i % 5})
            else:
                raise NotImplementedError(dataset)
        return out


@pytest.fixture
def conn(db_conn):
    apply_schema(db_conn)
    try:
        yield db_conn
    finally:
        clean(db_conn, START, END)


def count(conn, dataset=None):
    if dataset:
        return run_sql(conn, "SELECT count(*) FROM grid_raw WHERE dataset = %s", (dataset,))[0][0]
    return run_sql(conn, "SELECT count(*) FROM grid_raw")[0][0]


def test_backfill_twice_same_count(conn):
    client = SynthClient()
    kw = dict(datasets=("MID", "INDO", "DISEBSP"), days=4, end=END, window_days=1, max_storage_mb=None)

    r1 = backfill(conn, client, **kw)
    first = count(conn)
    assert first == 4 * 48 * 2 + 4 * 48 + 4 * 48  # MID price+volume, INDO, DISEBSP
    assert sum(r.rows_inserted for r in r1) == first
    assert client.calls == 12  # 3 datasets x 4 windows, nothing skipped on a fresh DB
    assert run_sql(conn, "SELECT count(*) FROM prices_hh")[0][0] == 4 * 48  # refreshed by backfill
    calls_after_first = client.calls

    # Resume: every window already has rows, so nothing is fetched and nothing changes.
    r2 = backfill(conn, client, **kw)
    assert client.calls == calls_after_first
    assert all(r.windows_skipped == r.windows for r in r2)
    assert count(conn) == first

    # Forced reload: fetched again, upsert inserts 0, count unchanged (chunks are compressed by now).
    r3 = backfill(conn, client, resume=False, **kw)
    assert client.calls > calls_after_first
    assert sum(r.rows_fetched for r in r3) == first
    assert sum(r.rows_inserted for r in r3) == 0
    assert count(conn) == first


def test_spilling_responses_do_not_skip_windows(conn):
    """Found on the first real 2-year run: a 60-day MID response spilled ~5 h into the next window and a
    row-based resume check ('any rows present') skipped that whole window, so MID/INDO/FUELHH loaded 7 of
    13 windows. With 6-hour windows and a 5 h spill (spill nearly as long as the window, the worst case for
    any row-based heuristic), every window must still be fetched and every row loaded."""
    client = SynthClient(spill_hours=5)
    kw = dict(datasets=("MID",), days=2, end=END, window_days=0.25, compress=False, refresh=False)

    backfill(conn, client, **kw)
    assert client.calls == 8  # 2 days / 6 h: no window skipped on a fresh DB
    assert count(conn, "MID") == 2 * 48 * 2 + 5 * 2 * 2  # every period x (price+volume), plus the last spill
    assert run_sql(conn, "SELECT count(*) FROM ingest_log WHERE dataset = 'MID'")[0][0] == 8

    # A second resume run finds every window logged and fetches nothing.
    before = client.calls
    backfill(conn, client, **kw)
    assert client.calls == before


def test_resume_trusts_the_log_not_the_rows(conn):
    """Coverage is recorded, not inferred: a logged window is skipped even if its rows are gone, and an
    unlogged window is fetched even if rows for it already exist (e.g. from spill-over)."""
    client = SynthClient()
    kw = dict(datasets=("INDO",), days=2, end=END, window_days=1, compress=False, refresh=False)
    backfill(conn, client, **kw)
    assert client.calls == 2

    conn.execute("DELETE FROM grid_raw WHERE dataset = 'INDO'")
    backfill(conn, client, **kw)
    assert client.calls == 2  # still logged -> skipped, rows or not

    conn.execute("DELETE FROM ingest_log WHERE dataset = 'INDO' AND window_start = %s", (START,))
    backfill(conn, client, **kw)
    assert client.calls == 3  # exactly the unlogged window was fetched again


def test_log_row_and_upsert_commit_together(conn):
    """If the log write fails, the window's rows must not be committed (no logged-but-empty or
    loaded-but-unlogged state). Simulated with a trigger that rejects log rows for one dataset."""
    conn.execute(
        "CREATE OR REPLACE FUNCTION _reject_disebsp() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NEW.dataset = 'DISEBSP' THEN RAISE EXCEPTION 'log write refused'; END IF; "
        "RETURN NEW; END $$"
    )
    conn.execute(
        "CREATE TRIGGER _reject BEFORE INSERT ON ingest_log FOR EACH ROW EXECUTE FUNCTION _reject_disebsp()"
    )
    try:
        with pytest.raises(Exception, match="log write refused"):
            backfill(
                conn, SynthClient(), datasets=("DISEBSP",), days=1, end=END, compress=False, refresh=False
            )
        assert count(conn, "DISEBSP") == 0
        assert run_sql(conn, "SELECT count(*) FROM ingest_log")[0][0] == 0
    finally:
        conn.execute("DROP TRIGGER IF EXISTS _reject ON ingest_log")
        conn.execute("DROP FUNCTION IF EXISTS _reject_disebsp()")


def test_backfill_compresses_and_reports_storage(conn):
    reports = backfill(conn, FakeClient(), datasets=("MID",), days=2, end=END, window_days=1)
    (rep,) = reports
    assert rep.chunks_compressed >= 1  # October 2025 chunks are older than 7 days
    assert rep.storage_mb_after > 0
    assert (
        run_sql(conn, "SELECT number_compressed_chunks FROM hypertable_compression_stats('grid_raw')")[0][0]
        >= 1
    )


def test_storage_limit_aborts_before_loading(conn):
    from tempo.ingest.backfill import StorageLimitExceeded

    with pytest.raises(StorageLimitExceeded):
        backfill(conn, FakeClient(), datasets=("MID",), days=2, end=END, window_days=1, max_storage_mb=0.001)
    assert count(conn) == 0
