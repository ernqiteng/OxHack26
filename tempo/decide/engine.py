"""run_decision(conn, now, forecaster, optimiser, run_id='live') -> decision_id.

Owner: Ernqi (Part A, docs/a.md item 3), written by Ayo.

The live pipeline: build_features(now) -> forecaster.predict -> optimiser.plan -> 48 forecasts rows and
48 decisions rows, one per target period, sharing one decided_at. Returns the decision_id of the first
period. What the rest of the system relies on (docs/a.md):

- one batch = 48 rows sharing one decided_at, run_id 'live' for the real system
- signed mw: + charge, - discharge, 0 hold
- a non-empty reason on every row (the optimiser explains trades too)
- forecast_id on every decision, pointing at that period's forecasts row

Running twice at the same decided_at replaces the earlier batch rather than duplicating it.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from tempo.features.build import build_features
from tempo.forecast.dataset import add_horizon_k
from tempo.sim.battery import Battery

LIVE_RUN_ID = "live"
ACTIONS = ("charge", "discharge", "hold")


def battery_from_settings(soc_mwh: float | None = None) -> Battery:
    from tempo.config import settings

    b = settings().battery
    return Battery(
        capacity_mwh=b.capacity_mwh,
        power_mw=b.power_mw,
        rt_efficiency=b.rt_efficiency,
        cycle_cost_gbp=b.cycle_cost_gbp,
        soc_mwh=b.capacity_mwh / 2 if soc_mwh is None else soc_mwh,
    )


def current_soc(conn, run_id: str, now: datetime, default: float) -> float:
    """Latest known state of charge for the run at or before now (battery_state), else the default."""
    row = conn.execute(
        "SELECT soc_mwh FROM battery_state WHERE run_id = %s AND ts <= %s ORDER BY ts DESC LIMIT 1",
        (run_id, now),
    ).fetchone()
    return float(row[0]) if row else default


def decision_rows(
    plan: pd.DataFrame, quantiles: pd.DataFrame, decided_at: datetime, run_id: str
) -> pd.DataFrame:
    """Pure: the 48 rows to write, checked against the contract. Index target_time."""
    if len(plan) != len(quantiles) or not plan.index.equals(quantiles.index):
        raise ValueError("plan and quantiles must share the same target_time index")
    rows = pd.DataFrame(index=plan.index)
    rows["decided_at"] = pd.Timestamp(decided_at).tz_convert("UTC")
    rows["action"] = plan["action"].astype(str)
    rows["mw"] = plan["mw"].astype(float)
    rows["expected_spread"] = plan["expected_spread"].astype(float)
    rows["reason"] = plan["reason"].fillna("").astype(str)
    rows["run_id"] = run_id
    for q in ("p10", "p50", "p90"):
        rows[q] = quantiles[q].astype(float)

    bad_action = ~rows.action.isin(ACTIONS)
    if bad_action.any():
        raise ValueError(f"unknown actions: {sorted(rows.action[bad_action].unique())}")
    sign_ok = (
        ((rows.action == "charge") & (rows.mw > 0))
        | ((rows.action == "discharge") & (rows.mw < 0))
        | ((rows.action == "hold") & (rows.mw == 0))
    )
    if not sign_ok.all():
        raise ValueError("mw sign disagrees with action")
    missing = (rows.action == "hold") & (rows.reason.str.strip() == "")
    if missing.any():
        rows.loc[missing, "reason"] = "hold: no profitable pair in the horizon"
    rows["expected_spread"] = rows["expected_spread"].where(rows["expected_spread"].notna(), None)
    return rows


def write_batch(conn, rows: pd.DataFrame, model: str) -> int:
    """Write forecasts then decisions for one batch; returns the first period's decision_id."""
    decided_at = rows["decided_at"].iloc[0].to_pydatetime()
    run_id = rows["run_id"].iloc[0]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM decisions WHERE decided_at = %s AND run_id = %s", (decided_at, run_id))
        cur.execute("DELETE FROM forecasts WHERE decided_at = %s AND run_id = %s", (decided_at, run_id))
        first_id = None
        for target, r in rows.iterrows():
            cur.execute(
                "INSERT INTO forecasts (decided_at, target_time, p10, p50, p90, model, run_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING forecast_id",
                (decided_at, target.to_pydatetime(), r.p10, r.p50, r.p90, model, run_id),
            )
            forecast_id = cur.fetchone()[0]
            spread = None if pd.isna(r.expected_spread) else float(r.expected_spread)
            cur.execute(
                "INSERT INTO decisions (decided_at, target_time, action, mw, reason, expected_spread, "
                "forecast_id, run_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING decision_id",
                (
                    decided_at,
                    target.to_pydatetime(),
                    r.action,
                    float(r.mw),
                    r.reason,
                    spread,
                    forecast_id,
                    run_id,
                ),
            )
            decision_id = cur.fetchone()[0]
            first_id = decision_id if first_id is None else first_id
    return int(first_id)


def run_decision(
    conn,
    now: datetime,
    forecaster,
    optimiser,
    run_id: str = LIVE_RUN_ID,
    *,
    battery: Battery | None = None,
    horizon: int = 48,
) -> int:
    """Forecast the next `horizon` periods from what is known at `now`, plan the battery, write the batch."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (UTC)")
    features = add_horizon_k(build_features(conn, now, horizon), now)
    quantiles = forecaster.predict(features)
    if battery is None:
        battery = battery_from_settings(current_soc(conn, run_id, now, default=None) or None)
    plan = optimiser.plan(quantiles, battery)
    rows = decision_rows(plan, quantiles, now, run_id)
    return write_batch(conn, rows, model=type(forecaster).__name__)
