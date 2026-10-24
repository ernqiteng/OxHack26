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

    def __init__(self, now: datetime | None = None, seed: int = 0) -> None:
        self.now = now or utc_now()
        self.seed = seed

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
                    "worker_id": f"tempo-worker-{i + 1}",
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
    """Real queries against TEMPO_DATABASE_URL. Phase 1 fills it in; same method names as SyntheticSource."""

    name = "tiger"

    def __init__(self, conn) -> None:
        self.conn = conn

    def __getattr__(self, item: str):
        raise NotImplementedError(f"DbSource.{item} lands in Phase 1 (docs/ayo.md)")


def pick_source(
    database_url: str | None, now: datetime | None = None
) -> tuple[SyntheticSource | DbSource, str]:
    """Return (source, note). Falls back to synthetic when the DB is unavailable or DbSource is incomplete."""
    if not database_url:
        return SyntheticSource(now), "TEMPO_DATABASE_URL not set: showing synthetic data"
    try:
        import psycopg

        conn = psycopg.connect(database_url, connect_timeout=5, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        return SyntheticSource(now), f"database unreachable ({type(exc).__name__}): showing synthetic data"
    return DbSource(conn), "connected to Tiger"
