"""Data access for the dashboard. Two sources behind one small interface:

- `SyntheticSource`: deterministic in-memory data shaped like the real tables, for local dev and tests.
- `DbSource(conn)`: real queries against Tiger (Phase 1). Until then every method raises NotImplementedError
  and the app falls back to synthetic with a banner.

Owner: Ayo. See docs/ayo.md. Table shapes follow docs/plan.md section 2.1.

TODO(Phase 1): replace `_synthetic_prices` with Ernqi's `tests.fixtures.synthetic.make_synthetic_market`
once it lands; the shape rules below copy that fixture's spec (cheap 01:00-05:00, dear 17:00-19:00,
windy even ISO weeks) so the swap changes numbers, not layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LONDON = ZoneInfo("Europe/London")
SHIFTS = (-2, -1, 0, 1, 2)
STRATEGIES = ("simple_rule", "persistence_greedy", "tempo", "perfect")
STRATEGY_LABELS = {
    "simple_rule": "Simple rule (charge 01:00-05:00, sell 17:00-19:00)",
    "persistence_greedy": "Persistence forecast + same optimiser",
    "tempo": "Tempo (LightGBM forecast + same optimiser)",
    "perfect": "Perfect knowledge of the future",
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def current_settlement_period(now: datetime | None = None) -> tuple[datetime, int]:
    """(settlement_date_local_midnight, period 1..50). Periods are defined in UK local time; period 1 starts
    at 00:00 local, so clock-change days have 46 or 50 periods. Keyed on UTC in the DB, local only here."""
    now = now or utc_now()
    local = now.astimezone(LONDON)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Subtract via UTC: two aware datetimes sharing one tzinfo subtract as wall-clock, which is wrong on
    # clock-change days (UK has 46 or 50 periods then).
    minutes = (now.astimezone(UTC) - midnight.astimezone(UTC)).total_seconds() / 60
    return midnight, int(minutes // 30) + 1


def period_start(now: datetime | None = None) -> datetime:
    now = now or utc_now()
    return now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)


# ---------------------------------------------------------------------------------------------
# Synthetic shapes
# ---------------------------------------------------------------------------------------------


def _price_shape(ts: pd.DatetimeIndex) -> np.ndarray:
    local = ts.tz_convert(LONDON)
    hour = local.hour.to_numpy() + local.minute.to_numpy() / 60
    shape = np.zeros(len(ts))
    shape += np.where((hour >= 1) & (hour < 5), -1.0, 0.0)
    shape += np.where((hour >= 17) & (hour < 19), 1.0, 0.0)
    shape += 0.3 * np.sin((hour - 9) / 24 * 2 * np.pi)
    windy = (local.isocalendar().week.to_numpy() % 2) == 0
    night = (hour >= 0) & (hour < 6)
    weekend_eve = (local.day_of_week.to_numpy() >= 5) & (hour >= 17) & (hour < 20)
    base = 60 + 40 * shape
    base = base - 30 * (windy & night) - 15 * weekend_eve
    return base


def _synthetic_prices(start: datetime, periods: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=periods, freq="30min", tz=UTC)
    price = _price_shape(idx) + rng.normal(0, 5, len(idx))
    return pd.DataFrame({"bucket": idx, "price": price, "volume": rng.uniform(200, 900, len(idx))})


@dataclass
class HoldInfo:
    decided_at: datetime
    target_time: datetime
    reason: str
    expected_spread: float


class SyntheticSource:
    """Deterministic stand-in for the database. `now` is injectable for tests and the replay animation."""

    name = "synthetic"
    sim_name = "synthetic (no replay)"

    def __init__(self, now: datetime | None = None, seed: int = 0) -> None:
        self.now = now or utc_now()
        self.seed = seed
        self.notes: dict[str, str] = {}

    def run_audit(self, decision_id: int) -> pd.DataFrame:
        return self.audit_rows(decision_id)

    # Live tab ---------------------------------------------------------------------------------
    def recent_prices(self, hours: int = 24) -> pd.DataFrame:
        start = period_start(self.now) - timedelta(hours=hours)
        return _synthetic_prices(start, hours * 2 + 1, self.seed)

    def next_forecast(self, periods: int = 48) -> pd.DataFrame:
        start = period_start(self.now) + timedelta(minutes=30)
        df = _synthetic_prices(start, periods, self.seed + 1).rename(
            columns={"bucket": "target_time", "price": "p50"}
        )
        width = 8 + 0.3 * np.arange(periods)  # uncertainty grows with horizon
        df["p10"] = df["p50"] - width
        df["p90"] = df["p50"] + width
        return df[["target_time", "p10", "p50", "p90"]]

    def todays_schedule(self) -> pd.DataFrame:
        fc = self.next_forecast()
        p50 = fc["p50"].to_numpy()
        order = np.argsort(p50)
        action = np.array(["hold"] * len(p50), dtype=object)
        mw = np.zeros(len(p50))
        cheap, dear = order[:4], order[-4:]
        if p50[dear].mean() * 0.9 - p50[cheap].mean() > 10:
            action[cheap], mw[cheap] = "charge", 1.0
            action[dear], mw[dear] = "discharge", -1.0
        reason = np.where(action == "hold", "spread below cost after 10% loss", "")
        return pd.DataFrame(
            {
                "target_time": fc["target_time"],
                "action": action,
                "mw": mw,
                "expected_spread": np.round(p50[dear].mean() - p50, 1),
                "reason": reason,
                "run_id": "live",
            }
        )

    def latest_hold(self) -> HoldInfo | None:
        sched = self.todays_schedule()
        holds = sched[sched.action == "hold"]
        if holds.empty:
            return None
        row = holds.iloc[0]
        return HoldInfo(
            decided_at=period_start(self.now),
            target_time=row.target_time.to_pydatetime(),
            reason="expected spread £11.20 did not cover £18.00 in losses "
            "(10% efficiency + £10/MWh degradation)",
            expected_spread=11.2,
        )

    # Replay tab -------------------------------------------------------------------------------
    def replay_week(self) -> pd.DataFrame:
        """One windy week, period by period: actual, p10/p50/p90, schedule mw, soc, cumulative pnl."""
        start = datetime(2026, 1, 5, tzinfo=UTC)  # ISO week 2, even => windy
        actual = _synthetic_prices(start, 7 * 48, self.seed + 2)
        fc = _synthetic_prices(start, 7 * 48, self.seed + 3)
        df = pd.DataFrame({"ts": actual.bucket, "actual": actual.price, "p50": fc.price})
        df["p10"], df["p90"] = df.p50 - 10, df.p50 + 10
        local_hour = df.ts.dt.tz_convert(LONDON).dt.hour
        df["mw"] = np.where(
            (local_hour >= 1) & (local_hour < 5),
            1.0,
            np.where((local_hour >= 17) & (local_hour < 19), -1.0, 0.0),
        )
        soc, cum, soc_path, pnl_path = 1.0, 0.0, [], []
        for mw, price in zip(df.mw, df.actual, strict=True):
            energy = mw * 0.5
            new_soc = float(np.clip(soc + (energy * 0.9487 if energy > 0 else energy / 0.9487), 0, 2))
            if new_soc == soc:
                energy = 0.0
            cum += -energy * price
            soc = new_soc
            soc_path.append(soc)
            pnl_path.append(cum)
        df["soc_mwh"], df["cum_pnl_gbp"] = soc_path, pnl_path
        return df

    # Timing audit tab -------------------------------------------------------------------------
    def recent_decisions(self, limit: int = 20) -> pd.DataFrame:
        rows = []
        for k in range(limit):
            decided = period_start(self.now) - timedelta(hours=6 * k)
            rows.append(
                {
                    "decision_id": 1000 - k,
                    "decided_at": decided,
                    "target_time": decided + timedelta(minutes=30),
                    "action": ["charge", "discharge", "hold"][k % 3],
                    "mw": [1.0, -1.0, 0.0][k % 3],
                    "reason": ["", "", "spread 9.8 < cost 18.0"][k % 3],
                    "run_id": "live",
                }
            )
        return pd.DataFrame(rows)

    def audit_rows(self, decision_id: int, failed_shift: int | None = None) -> pd.DataFrame:
        rng = np.random.default_rng(self.seed + decision_id)
        base = 120 + rng.normal(0, 10)
        rows = []
        for i, shift in enumerate(SHIFTS):
            pnl = base - 7.5 * shift**2 + rng.normal(0, 2)
            failed = shift == failed_shift
            rows.append(
                {
                    "decision_id": decision_id,
                    "shift": shift,
                    "pnl_gbp": None if failed else round(pnl, 2),
                    "pnl_delta_gbp": None if failed else round(pnl - base, 2),
                    "mode": "inprocess",
                    "fork_service_id": None,
                    "worker_id": None,
                    "started_at": self.now,
                    "finished_at": self.now + timedelta(seconds=40 + 5 * i),
                }
            )
        df = pd.DataFrame(rows)
        zero = df["shift"] == 0  # df.shift is the DataFrame method
        if df.loc[zero, "pnl_gbp"].notna().all():
            df.loc[zero, "pnl_delta_gbp"] = 0.0
            df["pnl_delta_gbp"] = df["pnl_gbp"] - float(df.loc[zero, "pnl_gbp"].iloc[0])
        return df

    def self_grade(self) -> dict:
        return {"pct_within_one_period": 71.0, "n_cycles": 38, "mean_cost_of_mistiming_gbp": 9.4}

    # Honesty tab ------------------------------------------------------------------------------
    def backtest_summary(self) -> pd.DataFrame:
        perfect = 4120.0
        totals = {"simple_rule": 1980.0, "persistence_greedy": 2410.0, "tempo": 2890.0, "perfect": perfect}
        return pd.DataFrame(
            {
                "strategy": [STRATEGY_LABELS[s] for s in STRATEGIES],
                "pnl_gbp": [totals[s] for s in STRATEGIES],
                "pct_of_perfect": [round(100 * totals[s] / perfect, 1) for s in STRATEGIES],
            }
        )

    def backtest_by_regime(self) -> pd.DataFrame:
        rows = []
        for regime, scale in (("calm", 0.6), ("windy", 1.4)):
            for s, pct in zip(STRATEGIES, (48, 58, 70, 100), strict=True):
                rows.append(
                    {
                        "regime": regime,
                        "strategy": s,
                        "pnl_gbp": round(1000 * scale * pct / 100, 1),
                        "pct_of_perfect": pct,
                    }
                )
        return pd.DataFrame(rows)

    def calibration(self) -> pd.DataFrame:
        nominal = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
        observed = np.array([0.14, 0.27, 0.49, 0.71, 0.86])
        return pd.DataFrame({"nominal": nominal, "observed": observed})

    def storage_stats(self) -> dict:
        return {"rows": 9_800_000, "before_bytes": 2.1e9, "after_bytes": 0.21e9, "ratio": 10.0}

    def weak_points(self) -> list[str]:
        return [
            "On calm summer weeks the simple rule captures nearly as much as Tempo; "
            "the spread is the edge, not the forecast.",
            "The p10-p90 band held 86% of actual prices against an 80% target: "
            "slightly under-confident, not over-confident.",
            "MID prices carry no publish time; availability is derived as period end + 10 min "
            "and stated here.",
            "We assume the battery can transact at the APX within-day index price; "
            "a real unit would trade day-ahead.",
        ]


class DbSource:
    """Real queries against TEMPO_DATABASE_URL, same method names as SyntheticSource.

    Every method degrades on its own: if its table is missing or empty (teammates' parts not landed yet) it
    returns the synthetic equivalent and records why in `notes[method]`, which the app shows as a banner on
    that tab. Results are cached for `ttl` seconds (docs/ayo.md: cache queries for 30 s).
    """

    name = "tiger"

    def __init__(
        self, conn, *, url: str | None = None, ttl: float = 30.0, now: datetime | None = None
    ) -> None:
        import threading

        from tempo.audit.refsim import resolve_sim

        self.conn = conn
        self.url = url
        self.ttl = ttl
        self.fallback = SyntheticSource(now)
        self.notes: dict[str, str] = {}
        self.sim_name = resolve_sim()[1]
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._decisions_synthetic = False

    # -- plumbing ---------------------------------------------------------------------------------
    def _df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        import psycopg

        with self._lock:
            try:
                cur = self.conn.execute(sql, params)
            except psycopg.OperationalError:
                if not self.url:
                    raise
                self.conn = psycopg.connect(self.url, connect_timeout=5, autocommit=True)
                cur = self.conn.execute(sql, params)
            cols = [d.name for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)

    def _cached(self, key: tuple, fn):
        import time

        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        value = fn()
        self._cache[key] = (time.monotonic(), value)
        return value

    def _try(self, method: str, fn, fallback, *, empty_ok: bool = False, empty_note: str = "no rows yet"):
        """Run fn(); on error or (unless empty_ok) an empty result, use fallback() and note why."""
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 - a missing table must not break the page
            self.notes[method] = (
                f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}. Showing synthetic data."
            )
            return fallback()
        empty = (isinstance(value, pd.DataFrame) and value.empty) or value is None
        if empty and not empty_ok:
            self.notes[method] = f"{empty_note}. Showing synthetic data."
            return fallback()
        self.notes.pop(method, None)
        return value

    def _synthetic(self, method: str, why: str):
        self.notes[method] = f"{why}. Showing synthetic data."
        return getattr(self.fallback, method)()

    # -- Live tab ---------------------------------------------------------------------------------
    def recent_prices(self, hours: int = 24) -> pd.DataFrame:
        sql = (
            "SELECT bucket, price, volume FROM prices_hh "
            "WHERE bucket > (SELECT max(bucket) FROM prices_hh) - make_interval(hours => %s) ORDER BY bucket"
        )
        return self._try(
            "recent_prices",
            lambda: self._cached(("prices", hours), lambda: self._df(sql, (hours,))),
            lambda: self.fallback.recent_prices(hours),
            empty_note="prices_hh is empty",
        )

    def next_forecast(self, periods: int = 48) -> pd.DataFrame:
        sql = (
            "SELECT target_time, p10, p50, p90 FROM forecasts WHERE run_id = 'live' AND decided_at = "
            "(SELECT max(decided_at) FROM forecasts WHERE run_id = 'live') ORDER BY target_time LIMIT %s"
        )
        return self._try(
            "next_forecast",
            lambda: self._cached(("forecast", periods), lambda: self._df(sql, (periods,))),
            lambda: self.fallback.next_forecast(periods),
            empty_note="no live forecasts yet",
        )

    def todays_schedule(self) -> pd.DataFrame:
        sql = (
            "SELECT target_time, action, mw, expected_spread, reason, run_id FROM decisions "
            "WHERE run_id = 'live' AND decided_at = "
            "(SELECT max(decided_at) FROM decisions WHERE run_id = 'live') "
            "ORDER BY target_time"
        )
        empty = pd.DataFrame(columns=["target_time", "action", "mw", "expected_spread", "reason", "run_id"])
        return self._try(
            "todays_schedule",
            lambda: self._cached(("schedule",), lambda: self._df(sql)),
            lambda: empty,
            empty_ok=True,
        )

    def latest_hold(self) -> HoldInfo | None:
        sql = (
            "SELECT decided_at, target_time, reason, expected_spread FROM decisions "
            "WHERE run_id = 'live' AND action = 'hold' ORDER BY decided_at DESC, target_time LIMIT 1"
        )

        def fetch():
            df = self._cached(("hold",), lambda: self._df(sql))
            if df.empty:
                return None
            r = df.iloc[0]
            spread = None if pd.isna(r.expected_spread) else float(r.expected_spread)
            return HoldInfo(r.decided_at, r.target_time, r.reason or "", spread)

        return self._try("latest_hold", fetch, lambda: None, empty_ok=True)

    # -- Replay tab (Phase 3) ---------------------------------------------------------------------
    def replay_week(self) -> pd.DataFrame:
        return self._synthetic("replay_week", "Replay week from backtest_results lands in Phase 3")

    # -- Timing audit tab -------------------------------------------------------------------------
    def recent_decisions(self, limit: int = 20) -> pd.DataFrame:
        sql = (
            "SELECT decision_id, decided_at, target_time, action, mw, reason, run_id FROM decisions "
            "WHERE run_id = 'live' ORDER BY decided_at DESC, target_time LIMIT %s"
        )
        df = self._try(
            "recent_decisions",
            lambda: self._df(sql, (limit,)),
            lambda: self.fallback.recent_decisions(limit),
            empty_note="no live decisions yet (Ernqi's run_decision, Phase 2); audit runs on synthetic rows",
        )
        self._decisions_synthetic = "recent_decisions" in self.notes
        return df

    def run_audit(self, decision_id: int) -> pd.DataFrame:
        if self._decisions_synthetic:
            return self.fallback.run_audit(decision_id)
        from tempo.audit.orchestrator import run_audit

        rows = run_audit(self.conn, decision_id, mode="inprocess")
        return pd.DataFrame([{**r.__dict__} for r in rows])

    def self_grade(self) -> dict:
        def fetch():
            from tempo.audit.selfgrade import self_grade

            return self_grade(self.conn, since=utc_now() - timedelta(days=30))

        return self._try("self_grade", fetch, self.fallback.self_grade)

    # -- Honesty tab ------------------------------------------------------------------------------
    _LATEST_RUN = "(SELECT max(run_id) FROM backtest_results)"

    def backtest_summary(self) -> pd.DataFrame:
        sql = (
            "SELECT strategy, sum(pnl_gbp) AS pnl_gbp, 100 * sum(pnl_gbp) / NULLIF(sum(perfect_pnl_gbp), 0) "
            f"AS pct_of_perfect FROM backtest_results WHERE run_id = {self._LATEST_RUN} GROUP BY strategy"
        )

        def fetch():
            df = self._cached(("summary",), lambda: self._df(sql))
            if df.empty:
                return df
            order = {s: i for i, s in enumerate(STRATEGIES)}
            df = df.assign(_o=df.strategy.map(order).fillna(99)).sort_values("_o").drop(columns="_o")
            df["strategy"] = df.strategy.map(lambda s: STRATEGY_LABELS.get(s, s))
            df["pct_of_perfect"] = df.pct_of_perfect.astype(float).round(1)
            return df.reset_index(drop=True)

        return self._try(
            "backtest_summary", fetch, self.fallback.backtest_summary, empty_note="backtest_results is empty"
        )

    def backtest_by_regime(self) -> pd.DataFrame:
        sql = (
            "SELECT regime, strategy, sum(pnl_gbp) AS pnl_gbp, "
            "100 * sum(pnl_gbp) / NULLIF(sum(perfect_pnl_gbp), 0) AS pct_of_perfect FROM backtest_results "
            f"WHERE run_id = {self._LATEST_RUN} AND regime IS NOT NULL GROUP BY regime, strategy"
        )
        return self._try(
            "backtest_by_regime",
            lambda: self._cached(("regime",), lambda: self._df(sql)),
            self.fallback.backtest_by_regime,
            empty_note="no regime rows in backtest_results",
        )

    def calibration(self) -> pd.DataFrame:
        return self._synthetic("calibration", "Calibration from Ernqi's reliability table lands in Phase 3")

    def storage_stats(self) -> dict:
        def fetch():
            from tempo.db.stats import storage_stats

            return self._cached(("storage",), lambda: storage_stats(self.conn))

        return self._try("storage_stats", fetch, self.fallback.storage_stats)

    def weak_points(self) -> list[str]:
        return self.fallback.weak_points()


def pick_source(
    database_url: str | None, now: datetime | None = None
) -> tuple[SyntheticSource | DbSource, str]:
    """Return (source, note). Falls back to synthetic only when the DB itself is unreachable."""
    if not database_url:
        return SyntheticSource(now), "TEMPO_DATABASE_URL not set: showing synthetic data"
    try:
        import psycopg

        conn = psycopg.connect(database_url, connect_timeout=5, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        return SyntheticSource(now), f"database unreachable ({type(exc).__name__}): showing synthetic data"
    return DbSource(conn, url=database_url, now=now), "connected to the database"
