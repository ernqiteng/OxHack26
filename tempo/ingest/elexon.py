"""Elexon Insights API client: fetch(), fetch_stream(), chunk_range(), normalise(). No API key needed.

Owner: Girik. See docs/girik.md and docs/needs.md B3.

Rules baked in here (the point-in-time guarantee starts at this file):
- start_time is always the API's `startTime` (UTC). Never derived from settlementDate + settlementPeriod,
  which breaks on clock-change days (46 or 50 periods).
- available_at is the API's publish time where it has one (publishTime / createdDateTime). MID has none,
  so it is derived: start_time + 30 min + MID_AVAILABILITY_DELAY_MIN (stated on the honesty panel).
- MID rows with volume == 0 are dropped (price is 0.0 on those rows; seen on both N2EX and, rarely, APX).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
GRID_RAW_COLUMNS = [
    "start_time",
    "available_at",
    "dataset",
    "series",
    "value",
    "settlement_date",
    "settlement_period",
]

RETRY_STATUSES = {429, 500, 502, 503, 504}


def base_url() -> str:
    return os.environ.get("ELEXON_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def mid_delay_min() -> int:
    return int(os.environ.get("MID_AVAILABILITY_DELAY_MIN", "10"))


# ---------------------------------------------------------------------------
# Dataset registry: where each dataset lives and how its window is expressed
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DatasetSpec:
    name: str
    bulk_path: str  # stream endpoint for history, or the per-day path for DISEBSP
    live_path: str  # non-stream endpoint for the poller (<= 7 days)
    window: str  # 'from_to' | 'publish' | 'settlement_date' | 'per_day'
    is_forecast: bool  # forecasts are published before start_time, so available_at < start_time is normal
    bulk_window_days: int = 60


DATASETS: dict[str, DatasetSpec] = {
    "MID": DatasetSpec("MID", "/datasets/MID/stream", "/balancing/pricing/market-index", "from_to", False),
    "WINDFOR": DatasetSpec("WINDFOR", "/datasets/WINDFOR/stream", "/datasets/WINDFOR", "publish", True),
    "NDF": DatasetSpec("NDF", "/datasets/NDF/stream", "/datasets/NDF", "publish", True),
    "INDO": DatasetSpec("INDO", "/demand/outturn/stream", "/demand/outturn", "settlement_date", False),
    "FUELHH": DatasetSpec("FUELHH", "/datasets/FUELHH/stream", "/datasets/FUELHH", "publish", False),
    "DISEBSP": DatasetSpec(
        "DISEBSP",
        "/balancing/settlement/system-prices/{date}",
        "/balancing/settlement/system-prices/{date}",
        "per_day",
        False,
        bulk_window_days=1,
    ),
}
FORECAST_DATASETS = frozenset(d.name for d in DATASETS.values() if d.is_forecast)


def window_params(spec: DatasetSpec, start: datetime, end: datetime) -> dict[str, str]:
    """Query parameters that select [start, end) for this dataset's endpoint."""
    s, e = _iso(start), _iso(end)
    if spec.window == "from_to":
        return {"from": s, "to": e}
    if spec.window == "publish":
        return {"publishDateTimeFrom": s, "publishDateTimeTo": e}
    if spec.window == "settlement_date":
        # inclusive settlement dates; the API ignores the time part
        return {
            "settlementDateFrom": start.date().isoformat(),
            "settlementDateTo": (end - timedelta(seconds=1)).date().isoformat(),
        }
    raise ValueError(f"{spec.name} is fetched per day, not by window")


def _iso(t: datetime) -> str:
    if t.tzinfo is None:
        raise ValueError("window bounds must be timezone-aware UTC")
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunk_range(start: datetime, end: datetime, days: int) -> Iterator[tuple[datetime, datetime]]:
    """Yield contiguous, non-overlapping [s, e) windows of at most `days` days covering [start, end)."""
    if days <= 0:
        raise ValueError("days must be positive")
    step = timedelta(days=days)
    s = start
    while s < end:
        e = min(s + step, end)
        yield s, e
        s = e


# ---------------------------------------------------------------------------
# HTTP client with retry; one request in flight at a time (it is a sync client)
# ---------------------------------------------------------------------------
class ElexonClient:
    def __init__(
        self,
        base: str | None = None,
        http: httpx.Client | None = None,
        max_attempts: int = 5,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout_s: float = 120.0,
    ):
        self.base = (base or base_url()).rstrip("/")
        self.http = http or httpx.Client(timeout=timeout_s, headers={"User-Agent": "tempo-oxhack/0.1"})
        self.max_attempts = max_attempts
        self.backoff_s = backoff_s
        self.sleep = sleep
        self.requests_made = 0

    def get(self, path: str, **params) -> list[dict]:
        """GET and return the row list. Retries 429/5xx with backoff; raises after max_attempts."""
        url = self.base + path
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                resp = self.http.get(url, params=params)
                self.requests_made += 1
            except httpx.TransportError as exc:
                last = exc
                self._wait(attempt, None, f"{exc!r}")
                continue
            if resp.status_code in RETRY_STATUSES:
                last = httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
                self._wait(attempt, resp.headers.get("Retry-After"), f"HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            return _rows(resp.json())
        raise RuntimeError(f"Elexon GET {path} failed after {self.max_attempts} attempts: {last}") from last

    def _wait(self, attempt: int, retry_after: str | None, why: str) -> None:
        if attempt + 1 >= self.max_attempts:
            return
        delay = self.backoff_s * (2**attempt)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning("elexon retry %d/%d after %s, sleeping %.1fs", attempt + 1, self.max_attempts, why, delay)
        self.sleep(delay)

    def fetch(self, dataset: str, **params) -> list[dict]:
        """Non-stream endpoint (<= 7 days). `date=` for per-day datasets."""
        spec = DATASETS[dataset]
        return self.get(_fill(spec.live_path, params), **params)

    def fetch_stream(self, dataset: str, **params) -> list[dict]:
        """Stream endpoint (history, not capped at 7 days). `date=` for per-day datasets."""
        spec = DATASETS[dataset]
        return self.get(_fill(spec.bulk_path, params), **params)

    def fetch_window(self, dataset: str, start: datetime, end: datetime, bulk: bool = True) -> list[dict]:
        """Fetch [start, end) for a dataset, handling the per-day DISEBSP endpoint transparently."""
        spec = DATASETS[dataset]
        if spec.window == "per_day":
            rows: list[dict] = []
            d = start.date()
            while datetime.combine(d, datetime.min.time(), tzinfo=UTC) < end:
                rows.extend(self.get(spec.bulk_path.format(date=d.isoformat())))
                d += timedelta(days=1)
            return rows
        path = spec.bulk_path if bulk else spec.live_path
        return self.get(path, **window_params(spec, start, end))

    def metadata_latest(self) -> dict[str, str]:
        """dataset -> lastUpdated (ISO string) from /datasets/metadata/latest."""
        return {r["dataset"]: r["lastUpdated"] for r in self.get("/datasets/metadata/latest")}


def _fill(path: str, params: dict) -> str:
    if "{date}" in path:
        d = params.pop("date", None)
        if d is None:
            raise ValueError("per-day endpoint needs date=YYYY-MM-DD")
        return path.format(date=d if isinstance(d, str) else date.isoformat(d))
    return path


def _rows(payload) -> list[dict]:
    # /datasets/{X} and system-prices wrap rows in {"data": [...]}; stream endpoints return a bare list.
    if isinstance(payload, dict):
        return payload.get("data", [])
    return payload


_default_client: ElexonClient | None = None


def default_client() -> ElexonClient:
    global _default_client
    if _default_client is None:
        _default_client = ElexonClient()
    return _default_client


def fetch(dataset: str, **params) -> list[dict]:
    return default_client().fetch(dataset, **params)


def fetch_stream(dataset: str, **params) -> list[dict]:
    return default_client().fetch_stream(dataset, **params)


# ---------------------------------------------------------------------------
# normalise(): API rows -> grid_raw long format
# ---------------------------------------------------------------------------
def normalise(dataset: str, rows: list[dict], mid_delay: int | None = None) -> pd.DataFrame:
    """Convert raw API rows for `dataset` into the grid_raw long format.

    Returns a DataFrame with GRID_RAW_COLUMNS, tz-aware UTC timestamps, no NaN values, and no duplicate
    primary keys. Returns an empty frame with the right columns for no rows.
    """
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}")
    if not rows:
        return _empty()
    raw = pd.DataFrame(rows)
    fn = _NORMALISERS[dataset]
    df = fn(raw, mid_delay if mid_delay is not None else mid_delay_min())
    df = df.dropna(subset=["value"])
    df["dataset"] = dataset
    df["series"] = df["series"].fillna("").astype(str)
    df["value"] = df["value"].astype(float)
    if "settlement_date" in df:
        df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce").dt.date
    else:
        df["settlement_date"] = None
    if "settlement_period" in df:
        df["settlement_period"] = df["settlement_period"].astype("Int64")
    else:
        df["settlement_period"] = pd.array([None] * len(df), dtype="Int64")
    df = df[GRID_RAW_COLUMNS].drop_duplicates(subset=["start_time", "available_at", "dataset", "series"])
    return df.reset_index(drop=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in GRID_RAW_COLUMNS})


def _utc(col: pd.Series, name: str) -> pd.Series:
    out = pd.to_datetime(col, utc=False, format="ISO8601")
    if not isinstance(out.dtype, pd.DatetimeTZDtype):
        # The API always sends 'Z'. A naive timestamp means the field changed shape; refuse to guess.
        raise ValueError(f"{name}: timestamps are not timezone-aware")
    return out.dt.tz_convert("UTC")


def _norm_mid(raw: pd.DataFrame, delay_min: int) -> pd.DataFrame:
    raw = raw[raw["volume"] != 0]
    start = _utc(raw["startTime"], "MID.startTime")
    avail = start + pd.Timedelta(minutes=30 + delay_min)
    common = {
        "start_time": start,
        "available_at": avail,
        "settlement_date": raw["settlementDate"],
        "settlement_period": raw["settlementPeriod"],
    }
    price = pd.DataFrame({**common, "series": raw["dataProvider"], "value": raw["price"]})
    volume = pd.DataFrame({**common, "series": raw["dataProvider"] + ":volume", "value": raw["volume"]})
    return pd.concat([price, volume], ignore_index=True)


def _norm_published(value_col: str, series_col: str | None):
    def fn(raw: pd.DataFrame, _delay: int) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "start_time": _utc(raw["startTime"], "startTime"),
                "available_at": _utc(raw["publishTime"], "publishTime"),
                "series": raw[series_col] if series_col else "",
                "value": raw[value_col],
            }
        )
        if "settlementDate" in raw:
            df["settlement_date"] = raw["settlementDate"]
        if "settlementPeriod" in raw:
            df["settlement_period"] = raw["settlementPeriod"]
        return df

    return fn


def _norm_disebsp(raw: pd.DataFrame, _delay: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "start_time": _utc(raw["startTime"], "DISEBSP.startTime"),
            "available_at": _utc(raw["createdDateTime"], "DISEBSP.createdDateTime"),
            "series": "",
            "value": raw["systemSellPrice"],
            "settlement_date": raw["settlementDate"],
            "settlement_period": raw["settlementPeriod"],
        }
    )


_NORMALISERS = {
    "MID": _norm_mid,
    "WINDFOR": _norm_published("generation", None),
    "NDF": _norm_published("demand", "boundary"),
    # needs.md B3 says `demand`; the real field on /demand/outturn/stream is initialDemandOutturn.
    "INDO": _norm_published("initialDemandOutturn", None),
    "FUELHH": _norm_published("generation", "fuelType"),
    "DISEBSP": _norm_disebsp,
}
