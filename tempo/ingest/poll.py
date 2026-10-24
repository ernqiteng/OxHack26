"""Live poller: watches /datasets/metadata/latest and upserts the last 2 days when a dataset moves.

Owner: Girik. See docs/girik.md Phase 2 and docs/todo_girik.md item 7.

- Metadata-driven: all six datasets (MID included) appear in /datasets/metadata/latest. A dataset is fetched
  only when its lastUpdated value changes; the first cycle fetches everything, which also closes any gap
  since the backfill (lookback defaults to 2 days).
- Non-stream endpoints (<= 7 days) for the live window, except NDF: /datasets/NDF rejects publish windows
  over 1 day (verified 24 Oct 2026), so NDF is fetched in 1-day windows.
- Rows go through the same normalise() + upsert_grid_raw() as the backfill, so the point-in-time stamping
  (publishTime, or start + 30 + delay for MID) and idempotency are identical. Clock-change days need no
  special handling: rows are keyed on the API's UTC startTime.
- A failed fetch is logged and retried next cycle (lastUpdated is only remembered after a successful
  upsert); the loop never dies on one bad response.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

import pandas as pd

from tempo.ingest.elexon import DATASETS, ElexonClient, chunk_range, normalise

log = logging.getLogger(__name__)

DEFAULT_DATASETS = ("MID", "WINDFOR", "NDF", "INDO", "FUELHH", "DISEBSP")
# Live (non-stream) window caps per dataset, in days. NDF's is 1 day; the others accept 7.
LIVE_WINDOW_DAYS = {"NDF": 1}


class Poller:
    def __init__(
        self,
        client: ElexonClient,
        sink: Callable[[pd.DataFrame], int],
        datasets: Iterable[str] = DEFAULT_DATASETS,
        lookback: timedelta = timedelta(days=2),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.client = client
        self.sink = sink  # e.g. lambda df: upsert_grid_raw(conn, df)
        self.datasets = tuple(datasets)
        self.lookback = lookback
        self.clock = clock
        self.last_seen: dict[str, str] = {}

    def fetch_recent(self, dataset: str) -> list[dict]:
        """The last `lookback` of `dataset` from its live endpoint, split to respect its window cap."""
        end = self.clock()
        start = end - self.lookback
        days = LIVE_WINDOW_DAYS.get(dataset, 7)
        rows: list[dict] = []
        for s, e in chunk_range(start, end, days):
            rows.extend(self.client.fetch_window(dataset, s, e, bulk=False))
        return rows

    def poll_once(self) -> dict[str, int]:
        """One cycle. Returns {dataset: rows inserted} for the datasets that were fetched."""
        meta = self.client.metadata_latest()
        fetched: dict[str, int] = {}
        for ds in self.datasets:
            updated = meta.get(ds)
            if updated is None:
                log.warning("poll %s: not in /datasets/metadata/latest, skipped", ds)
                continue
            if self.last_seen.get(ds) == updated:
                continue
            try:
                t0 = time.perf_counter()
                df = normalise(ds, self.fetch_recent(ds))
                inserted = self.sink(df)
            except Exception:  # noqa: BLE001 - one bad dataset must not stop the others or the loop
                log.exception("poll %s: fetch/upsert failed, retrying next cycle", ds)
                continue
            self.last_seen[ds] = updated  # only after a successful upsert
            fetched[ds] = inserted
            newest = df["start_time"].max() if len(df) else None
            log.info(
                "poll %s: lastUpdated %s, %d rows fetched, %d new, newest start %s, %.1fs",
                ds, updated, len(df), inserted, newest, time.perf_counter() - t0,
            )  # fmt: skip
        return fetched

    def run(
        self,
        interval_s: float = 60.0,
        iterations: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Poll forever (or `iterations` times). Exceptions in a cycle are logged, never raised."""
        n = 0
        while iterations is None or n < iterations:
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 - e.g. metadata endpoint down: wait and try again
                log.exception("poll cycle failed, retrying in %.0fs", interval_s)
            n += 1
            if iterations is None or n < iterations:
                sleep(interval_s)


def assert_known(datasets: Iterable[str]) -> None:
    unknown = [d for d in datasets if d not in DATASETS]
    if unknown:
        raise ValueError(f"unknown datasets: {unknown}")
