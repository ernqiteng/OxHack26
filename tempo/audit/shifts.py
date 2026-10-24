"""replay_shift(conn, decision_id, shift, run_id) -> pnl_gbp.

In-process replay, writes battery_state under run_id.

Owner: Ayo. See docs/ayo.md Phase 1 task 1.

A decision is one row of a 48-row batch written by `run_decision` (same `decided_at`, same `run_id`). Replay
takes the whole batch as the schedule, shifts it by `shift` periods (positive = later), fills the periods
that roll in from outside the window with hold, prices it at actual `prices_hh`, starts from the original
run's SoC at `decided_at`, simulates, and writes the SoC and cumulative PnL path to `battery_state` under
`run_id`. Same database contents in, same number out.

`battery_state.ts` convention: the state at the END of the period, i.e. `target_time + 30 min`. The starting
SoC is therefore the latest original-run row with `ts <= decided_at`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np

from tempo.audit.refsim import resolve_sim
from tempo.config import BatteryParams, settings

PERIOD = timedelta(minutes=30)
LIVE_RUN_ID = "live"


class ReplayError(Exception):
    """The decision cannot be replayed (missing decision, missing prices, forbidden run_id)."""


@dataclass
class Schedule:
    decision_id: int
    decided_at: datetime
    run_id: str
    target_times: list[datetime]
    mw: np.ndarray


def shift_schedule(mw: np.ndarray, shift: int) -> np.ndarray:
    """np.roll by `shift`; periods that wrap around become hold (0 MW) instead of reappearing."""
    mw = np.asarray(mw, dtype=float)
    out = np.roll(mw, shift)
    if shift > 0:
        out[:shift] = 0.0
    elif shift < 0:
        out[shift:] = 0.0
    return out


def load_schedule(conn, decision_id: int) -> Schedule:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT decided_at, run_id FROM decisions WHERE decision_id = %s",
            (decision_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ReplayError(f"decision {decision_id} not found")
        decided_at, run_id = row
        cur.execute(
            "SELECT target_time, mw FROM decisions WHERE decided_at = %s AND run_id = %s "
            "ORDER BY target_time",
            (decided_at, run_id),
        )
        rows = cur.fetchall()
    return Schedule(
        decision_id=decision_id,
        decided_at=decided_at,
        run_id=run_id,
        target_times=[r[0] for r in rows],
        mw=np.array([float(r[1] or 0.0) for r in rows]),
    )


def load_prices(conn, target_times: list[datetime]) -> np.ndarray:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bucket, price FROM prices_hh WHERE bucket >= %s AND bucket <= %s",
            (target_times[0], target_times[-1]),
        )
        found = {b: float(p) for b, p in cur.fetchall() if p is not None}
    missing = [t for t in target_times if t not in found]
    if missing:
        raise ReplayError(
            f"{len(missing)} of {len(target_times)} periods have no actual price in prices_hh "
            f"(first missing {missing[0].isoformat()}); "
            "a decision can only be replayed once its periods settle"
        )
    return np.array([found[t] for t in target_times])


def load_start_soc(conn, run_id: str, decided_at: datetime, capacity_mwh: float) -> float:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT soc_mwh FROM battery_state WHERE run_id = %s AND ts <= %s ORDER BY ts DESC LIMIT 1",
            (run_id, decided_at),
        )
        row = cur.fetchone()
    return float(row[0]) if row else capacity_mwh / 2


def cumulative_pnl(sim: SimpleNamespace, battery, mw: np.ndarray, prices: np.ndarray) -> np.ndarray:
    """Cumulative PnL after each period, from the simulator itself (prefix runs), so it matches the
    simulator's own accounting of losses, clipping and cycle cost without re-implementing physics."""
    return np.array([sim.simulate(battery, mw[: k + 1], prices[: k + 1]).pnl_gbp for k in range(len(mw))])


def write_battery_state(
    conn, run_id: str, target_times: list[datetime], soc: np.ndarray, cum: np.ndarray
) -> None:
    ts = [t + PERIOD for t in target_times]
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM battery_state WHERE run_id = %s AND ts >= %s AND ts <= %s", (run_id, ts[0], ts[-1])
        )
        cur.executemany(
            "INSERT INTO battery_state (ts, soc_mwh, cum_pnl_gbp, run_id) VALUES (%s, %s, %s, %s)",
            [(t, float(s), float(c), run_id) for t, s, c in zip(ts, soc, cum, strict=True)],
        )


def _battery(sim: SimpleNamespace, params: BatteryParams, soc: float):
    base = sim.Battery()
    fields = dict(
        capacity_mwh=params.capacity_mwh,
        power_mw=params.power_mw,
        rt_efficiency=params.rt_efficiency,
        cycle_cost_gbp=params.cycle_cost_gbp,
        soc_mwh=soc,
    )
    return replace(base, **{k: v for k, v in fields.items() if hasattr(base, k)})


def replay_shift(
    conn,
    decision_id: int,
    shift: int,
    run_id: str,
    *,
    sim: SimpleNamespace | None = None,
    battery_params: BatteryParams | None = None,
) -> float:
    """Replay `decision_id`'s schedule shifted by `shift` periods; write battery_state under `run_id`;
    return pnl_gbp. `sim` defaults to `resolve_sim()` (Ernqi's simulator when merged)."""
    if run_id == LIVE_RUN_ID:
        raise ReplayError("replay must never write under run_id='live'")
    if not -47 <= shift <= 47:
        raise ReplayError(f"shift {shift} out of range")
    sim = sim or resolve_sim()[0]
    params = battery_params or settings().battery

    sched = load_schedule(conn, decision_id)
    prices = load_prices(conn, sched.target_times)
    soc0 = load_start_soc(conn, sched.run_id, sched.decided_at, params.capacity_mwh)
    battery = _battery(sim, params, soc0)

    mw = shift_schedule(sched.mw, shift)
    result = sim.simulate(battery, mw, prices)
    soc = np.asarray(result.soc_path, dtype=float)
    if len(soc) == len(mw) + 1:  # simulator included the starting SoC
        soc = soc[1:]
    cum = cumulative_pnl(sim, battery, mw, prices)
    write_battery_state(conn, run_id, sched.target_times, soc, cum)
    return float(result.pnl_gbp)
