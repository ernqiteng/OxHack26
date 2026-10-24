"""Two-year bulk load of MID, WINDFOR, NDF, INDO, FUELHH, DISEBSP into grid_raw. Resumable.

Owner: Girik. See docs/girik.md Phase 1.

Order matters for the Tiger free service (750 MiB cap): small datasets first, NDF (the heavy one) last,
chunks compressed after every dataset, and the run aborts before the service goes read-only if
storage crosses max_storage_mb.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg

from tempo.db.conn import refresh_caggs, run_sql, upsert_grid_raw
from tempo.db.stats import compress_chunks, storage_mb
from tempo.ingest.elexon import DATASETS, ElexonClient, chunk_range, normalise

log = logging.getLogger(__name__)

# Small and essential first; NDF is ~60% of all rows and the only one we could trim if storage bites.
DEFAULT_ORDER = ("MID", "DISEBSP", "INDO", "WINDFOR", "FUELHH", "NDF")


class StorageLimitExceeded(RuntimeError):
    pass


@dataclass
class LoadReport:
    dataset: str
    windows: int = 0
    windows_skipped: int = 0
    rows_fetched: int = 0
    rows_inserted: int = 0
    seconds: float = 0.0
    storage_mb_after: float = 0.0
    chunks_compressed: int = 0
    coverage: Coverage | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class Coverage:
    """Does the loaded data actually span [start, end)? A half-load raises no error anywhere else."""

    dataset: str
    start: datetime
    end: datetime
    first: datetime | None
    last: datetime | None
    days_with_data: int
    gaps: list[tuple[datetime, datetime]]  # (last day with data before the gap, first day after); any
    # missing day counts, which is stricter than 'longer than a day': a missing day of prices is not fine

    @property
    def expected_days(self) -> int:
        return max(1, round((self.end - self.start).total_seconds() / 86400))

    @property
    def problems(self) -> list[str]:
        if self.first is None:
            return ["no rows"]
        out = []
        if self.first > self.start + timedelta(days=1):
            out.append(f"starts late: first {self.first:%Y-%m-%d %H:%M} vs requested {self.start:%Y-%m-%d}")
        if self.last < self.end - timedelta(days=1):
            out.append(f"ends early: last {self.last:%Y-%m-%d %H:%M} vs requested {self.end:%Y-%m-%d}")
        for a, b in self.gaps:
            missing = (b - a).days - 1  # a and b both have data; the days strictly between them do not
            out.append(f"gap: no data between {a:%Y-%m-%d} and {b:%Y-%m-%d} ({missing} missing days)")
        return out

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        if self.first is None:
            return f"{self.dataset}: NO ROWS in requested range"
        status = "ok" if self.ok else "PROBLEMS: " + "; ".join(self.problems)
        return (
            f"{self.dataset} coverage {self.first:%Y-%m-%d}..{self.last:%Y-%m-%d}, "
            f"{self.days_with_data}/{self.expected_days} days with data, {status}"
        )


def coverage(conn: psycopg.Connection, dataset: str, start: datetime, end: datetime) -> Coverage:
    """Span and day-gaps of `dataset` within [start, end), keyed on the fetch-window column."""
    col = window_key_column(dataset)
    days = [
        r[0]
        for r in run_sql(
            conn,
            f"SELECT DISTINCT date_trunc('day', {col}) FROM grid_raw "  # noqa: S608
            f"WHERE dataset = %s AND {col} >= %s AND {col} < %s ORDER BY 1",
            (dataset, start, end),
        )
    ]
    if not days:
        return Coverage(dataset, start, end, None, None, 0, [])
    first, last = run_sql(
        conn,
        f"SELECT min({col}), max({col}) FROM grid_raw WHERE dataset = %s AND {col} >= %s AND {col} < %s",  # noqa: S608
        (dataset, start, end),
    )[0]
    gaps = [(a, b) for a, b in zip(days, days[1:], strict=False) if b - a > timedelta(days=1)]
    return Coverage(dataset, start, end, first, last, len(days), gaps)


def window_key_column(dataset: str) -> str:
    """Column the fetch window selects on: available_at for publish-time datasets, start_time otherwise."""
    return "available_at" if DATASETS[dataset].window == "publish" else "start_time"


def window_covered(conn: psycopg.Connection, dataset: str, start: datetime, end: datetime) -> bool:
    """True if this exact window was fetched before, per ingest_log.

    Coverage is recorded, never inferred from grid_raw rows. The first 2-year run inferred it ('any rows in
    the window'): Elexon's from/to return whole settlement days, each 60-day response spilled a few hours
    into the next window, and MID, INDO and FUELHH silently loaded 7 of 13 windows. Any row-based
    heuristic fails somewhere (spill-over, sparse datasets, short windows); the log is exact."""
    rows = run_sql(
        conn,
        "SELECT 1 FROM ingest_log WHERE dataset = %s AND window_start = %s AND window_end = %s",
        (dataset, start, end),
    )
    return bool(rows)


def record_window(conn: psycopg.Connection, dataset: str, start: datetime, end: datetime, rows: int) -> None:
    conn.execute(
        "INSERT INTO ingest_log (dataset, window_start, window_end, rows) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (dataset, window_start, window_end) "
        "DO UPDATE SET rows = EXCLUDED.rows, fetched_at = now()",
        (dataset, start, end, rows),
    )


def load_dataset(
    conn: psycopg.Connection,
    client: ElexonClient,
    dataset: str,
    start: datetime,
    end: datetime,
    window_days: int | None = None,
    resume: bool = True,
    compress: bool = True,
    on_window: Callable[[str, datetime, datetime, int, int], None] | None = None,
    max_storage_mb: float | None = None,
    storage_fn: Callable[[], float] | None = None,
) -> LoadReport:
    """Load one dataset over [start, end) window by window. Resume skips windows already covered
    (see window_covered); pass resume=False to force a reload, which upsert makes safe.

    Storage is checked before every window and chunks are compressed after every window, so at most one
    window's rows are ever uncompressed. Compressing only at the end of a dataset let 9 NDF windows
    (~1.4M rows) pile up uncompressed on the 750 MB Tiger free service, which goes read-only at the cap."""
    spec = DATASETS[dataset]
    days = window_days or spec.bulk_window_days
    rep = LoadReport(dataset)
    storage_fn = storage_fn or (lambda: storage_mb(conn))
    t0 = time.perf_counter()
    for s, e in chunk_range(start, end, days):
        rep.windows += 1
        if resume and window_covered(conn, dataset, s, e):
            rep.windows_skipped += 1
            continue
        if max_storage_mb is not None:
            used = storage_fn()
            if used > max_storage_mb:
                raise StorageLimitExceeded(
                    f"{used:.0f} MB used > {max_storage_mb} MB limit; stopped before {dataset} "
                    f"{s:%Y-%m-%d}..{e:%Y-%m-%d} (resume picks up here)"
                )
        rows = client.fetch_window(dataset, s, e, bulk=True)
        df = normalise(dataset, rows)
        with conn.transaction():  # the upsert and its log row commit together, or not at all
            inserted = upsert_grid_raw(conn, df)
            record_window(conn, dataset, s, e, len(df))
        rep.rows_fetched += len(df)
        rep.rows_inserted += inserted
        if compress:
            rep.chunks_compressed += compress_chunks(conn)
        if on_window:
            on_window(dataset, s, e, len(df), inserted)
    rep.coverage = coverage(conn, dataset, start, end)
    if not rep.coverage.ok:
        log.warning(rep.coverage.summary())
        rep.errors.extend(rep.coverage.problems)
    rep.storage_mb_after = storage_mb(conn)
    rep.seconds = time.perf_counter() - t0
    return rep


def backfill(
    conn: psycopg.Connection,
    client: ElexonClient,
    datasets: tuple[str, ...] = DEFAULT_ORDER,
    days: int = 730,
    end: datetime | None = None,
    window_days: int | None = None,
    resume: bool = True,
    compress: bool = True,
    max_storage_mb: float | None = None,
    refresh: bool = True,
    report: Callable[[str], None] = log.info,
    storage_fn: Callable[[], float] | None = None,
) -> list[LoadReport]:
    """Load every dataset for [end - days, end). Compresses after each window, reports storage, and raises
    StorageLimitExceeded before any window once storage_fn() (default pg_database_size; pass
    tiger_storage_mb against Tiger) is above max_storage_mb.

    Pass the same `end` as the original run when resuming: ingest_log keys on exact window bounds."""
    # Midnight-aligned windows: the per-day DISEBSP endpoint and Elexon's whole-day from/to semantics then
    # fetch each day exactly once. Today's partial day is the live poller's job (Phase 2).
    end = end or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    reports: list[LoadReport] = []
    for ds in datasets:
        rep = load_dataset(
            conn,
            client,
            ds,
            start,
            end,
            window_days=window_days,
            resume=resume,
            compress=compress,
            on_window=lambda d, s, e, n, i: report(f"{d} {s:%Y-%m-%d}..{e:%Y-%m-%d}: {n} rows, {i} new"),
            max_storage_mb=max_storage_mb,
            storage_fn=storage_fn,
        )
        reports.append(rep)
        report(
            f"{ds}: {rep.rows_inserted} new / {rep.rows_fetched} fetched in {rep.windows} windows "
            f"({rep.windows_skipped} skipped), {rep.seconds:.0f}s, {rep.chunks_compressed} chunks compressed,"
            f" "
            f"storage {rep.storage_mb_after:.0f} MiB"
        )
        report(rep.coverage.summary())
    if refresh and "MID" in datasets:
        refresh_caggs(conn, start, end + timedelta(days=7))
        (n,) = run_sql(conn, "SELECT count(*) FROM prices_hh")[0]
        report(f"aggregates refreshed: prices_hh has {n} rows")
    return reports


def lookahead_check(conn: psycopg.Connection) -> int:
    """Rows that claim something impossible about time. Must be 0 (docs/girik.md Gate 1).

    - INDO, FUELHH, DISEBSP: available_at is Elexon's own publish time, so one in the future is corrupt data.
    - MID: available_at is our derived stamp (start + 30 + delay). Elexon publishes MID during the period
      (seen live: the 18:30 period at 18:42), so for the in-progress period the stamp is legitimately after
      now(); that is conservative, not a leak, and build_features ignores the row until then. What must not
      exist is a MID price for a period that has not started.
    - WINDFOR, NDF are forecasts: future start_time is their purpose, and their publishTime is checked by
      the publish-time rule above only through the datasets listed there.
    """
    (n,) = run_sql(
        conn,
        "SELECT count(*) FROM grid_raw WHERE "
        "(dataset IN ('INDO', 'FUELHH', 'DISEBSP') AND available_at > now()) "
        "OR (dataset IN ('WINDFOR', 'NDF') AND available_at > now()) "
        "OR (dataset = 'MID' AND start_time > now())",
    )[0]
    return n
