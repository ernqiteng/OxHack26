"""JSON layer over the dashboard's data source, for the Next.js frontend in `web/`.

Owner: Ayo. Every endpoint reads the same `pick_source()` object the Streamlit dashboard uses, so it shows
Tiger data when TEMPO_DATABASE_URL is reachable and synthetic data (labelled in /api/status) otherwise.
Run with `make api` (uvicorn on 127.0.0.1:8000); the frontend proxies /api/* to it.
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from tempo.dashboard.data import (
    HEADLINE_STRATEGY,
    SHIFTS,
    STRATEGY_LABELS,
    calibration_sentence,
    current_settlement_period,
    utc_now,
)
from tempo.dashboard.jobs import hero_sentence

app = FastAPI(title="Tempo API")
app.add_middleware(
    CORSMiddleware,
    # 3000: web/ (old frontend). 3001: pitch/ (dev server and `npm start`).
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# DbSource holds one psycopg connection; FastAPI runs sync endpoints on a thread pool.
_LOCK = threading.Lock()
ACTION_LABEL = {"charge": "charge", "discharge": "sell", "hold": "hold"}
SHIFT_LABELS = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}


@lru_cache(maxsize=1)
def source():
    from tempo.config import settings
    from tempo.dashboard.data import pick_source

    return pick_source(settings().database_url)


def _clean(v):
    """One JSON-safe scalar: timestamps to ISO strings, NaN/NaT to None, numpy to Python."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        if pd.isna(v):
            return None
        return pd.Timestamp(v).isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, np.bool_):
        return bool(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def records(df: pd.DataFrame | None, cols: list[str] | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def _main_pct(summary: pd.DataFrame) -> float | None:
    if summary.empty:
        return None
    row = summary[summary.strategy == STRATEGY_LABELS[HEADLINE_STRATEGY]]
    return None if row.empty else float(row.pct_of_perfect.iloc[0])


@app.get("/api/status")
def status() -> dict:
    src, note = source()
    return {"source": src.name, "note": note, "simulator": getattr(src, "sim_name", None), "notes": src.notes}


@app.get("/api/live")
def live() -> dict:
    src, _ = source()
    now = utc_now()
    with _LOCK:
        clock = getattr(src, "fallback", src)  # synthetic data follows the wall clock
        clock.now = now
        midnight, period = current_settlement_period(now)
        prices = src.recent_prices(24)
        fc = src.next_forecast()
        sched = src.todays_schedule()
        battery = src.battery_state()
        hold = src.latest_hold()
        summary = src.backtest_summary()
    plan = fc.copy()
    if not sched.empty:
        plan = plan.merge(sched[["target_time", "action", "mw", "reason"]], on="target_time", how="left")
    upcoming = sched[sched.action != "hold"] if not sched.empty else sched
    nxt = None
    if not upcoming.empty:
        r = upcoming.iloc[0]
        nxt = {
            "action": r.action,
            "label": ACTION_LABEL.get(r.action, r.action),
            "mw": _clean(r.mw),
            "target_time": _clean(r.target_time),
        }
    return {
        "now": now.isoformat(),
        "period": period,
        "latest_price": _clean(prices.price.iloc[-1]) if not prices.empty else None,
        "prices": records(prices, ["bucket", "price"]),
        "plan": records(plan, ["target_time", "p10", "p50", "p90", "action", "mw", "reason"]),
        "next": nxt,
        "battery": {k: _clean(v) for k, v in battery.items()} if battery else None,
        "hold": None
        if hold is None
        else {
            "target_time": _clean(hold.target_time),
            "reason": hold.reason,
            "expected_spread": _clean(hold.expected_spread),
        },
        "captured_pct": _main_pct(summary),
        "notes": src.notes,
    }


@app.get("/api/decisions")
def decisions(limit: int = 40) -> dict:
    """The hero map: recent replayable decisions as markers on the price line around them."""
    src, _ = source()
    with _LOCK:
        dec = src.recent_decisions(limit)
        if dec.empty:
            return {"decisions": [], "prices": []}
        span_h = (pd.Timestamp(utc_now()) - pd.Timestamp(dec.target_time.min())).total_seconds() / 3600
        hours = int(min(max(span_h + 6, 24), 24 * 14))
        prices = src.recent_prices(hours)
    return {
        "decisions": records(
            dec, ["decision_id", "decided_at", "target_time", "action", "mw", "reason", "run_id"]
        ),
        "prices": records(prices, ["bucket", "price"]),
    }


def _decision(src, decision_id: int) -> pd.Series:
    dec = src.recent_decisions(200)
    row = dec[dec.decision_id == decision_id]
    if row.empty:
        raise HTTPException(404, f"decision {decision_id} is not among the replayable decisions")
    return row.iloc[0]


@app.get("/api/decisions/{decision_id}/summary")
def decision_summary(decision_id: int) -> dict:
    """A plain-English summary built only from stored numbers (no language model, nothing invented)."""
    src, _ = source()
    with _LOCK:
        d = _decision(src, decision_id)
        target = pd.Timestamp(d.target_time)
        span = (pd.Timestamp(utc_now()) - target).total_seconds() / 3600
        prices = src.recent_prices(int(min(max(span + 30, 24), 24 * 14)))
    local = target.tz_convert("Europe/London")
    decided = pd.Timestamp(d.decided_at).tz_convert("Europe/London")
    verb = {"charge": "charge", "discharge": "sell", "hold": "hold"}.get(d.action, d.action)
    parts = [
        f"At {decided:%H:%M on %a %d %b} Tempo decided to {verb} {abs(float(d.mw or 0)):.0f} MW "
        f"in the settlement period starting {local:%H:%M}."
    ]
    if not prices.empty:
        p = prices.set_index(pd.to_datetime(prices.bucket, utc=True)).price
        day = p[(p.index >= target - timedelta(hours=12)) & (p.index <= target + timedelta(hours=12))]
        at = p.get(target)
        if at is not None and not day.empty:
            rank = int((day < at).sum()) + 1
            parts.append(
                f"The price that period settled at £{at:,.2f}/MWh, number {rank} of {len(day)} "
                f"from cheapest in the 24 hours around it (range £{day.min():,.2f} to £{day.max():,.2f})."
            )
            good = (d.action == "charge" and rank <= len(day) / 3) or (
                d.action == "discharge" and rank >= 2 * len(day) / 3
            )
            parts.append(
                "That puts it in the right third of the day for this action."
                if good
                else "That is not in the obvious third of the day for this action, "
                "so the timing audit matters here."
            )
    if isinstance(d.reason, str) and d.reason:
        parts.append(f"Stored reason: {d.reason}.")
    parts.append(
        "Run the timing audit to replay this decision 30 and 60 minutes earlier and later on settled prices."
    )
    title = f"{verb.capitalize()} at {local:%H:%M}, {local:%a %d %b}"
    return {"title": title, "text": " ".join(parts), "run_id": d.run_id, "action": d.action}


@app.post("/api/decisions/{decision_id}/audit")
def audit(decision_id: int) -> dict:
    """Timing audit, in-process: replay the decision at each of the five shifts."""
    src, _ = source()
    t0 = time.monotonic()
    with _LOCK:
        d = _decision(src, decision_id)
        rows = src.run_audit(decision_id)
    elapsed = time.monotonic() - t0
    rows = rows.sort_values("shift")
    out = records(rows, ["shift", "pnl_gbp", "pnl_delta_gbp", "mode", "worker_id"])
    for r in out:
        r["label"] = SHIFT_LABELS.get(r["shift"], str(r["shift"]))
    return {
        "rows": out,
        "sentence": hero_sentence(rows, d.action),
        "elapsed_s": round(elapsed, 2),
        "simulator": getattr(src, "sim_name", None),
        "shifts": list(SHIFTS),
    }


# Fork audits run in a background thread (tempo.dashboard.jobs.AuditJob); the pitch site polls their progress.
# The free tier has one fork slot, so only one may run at a time.
_JOBS: dict[int, object] = {}
_JOB_ACTIONS: dict[int, str] = {}


def _fork_status(decision_id: int, job) -> dict:
    states, events = job.progress.snapshot()
    out = {
        "decision_id": decision_id,
        "done": bool(job.done),
        "error": job.error,
        "running_s": round(job.running_s, 1),
        "states": {str(k): v for k, v in states.items()},
        "workers": {str(k): v for k, v in job.progress.workers.items()},
        "log": [
            {"t": round(e.elapsed_s, 1), "shift": e.shift, "state": e.state, "message": e.message}
            for e in events[-30:]
        ],
        "note": getattr(job, "note", None),
        "rows": [],
        "sentence": None,
    }
    if job.done and job.rows is not None and not job.rows.empty:
        rows = job.rows.sort_values("shift")
        cols = ["shift", "pnl_gbp", "pnl_delta_gbp", "mode", "worker_id", "fork_service_id"]
        out["rows"] = records(rows, cols)
        for r in out["rows"]:
            r["label"] = SHIFT_LABELS.get(r["shift"], str(r["shift"]))
        action = _JOB_ACTIONS.get(decision_id)
        out["sentence"] = hero_sentence(rows, action)
    return out



@app.post("/api/decisions/{decision_id}/fork-audit")
def start_fork_audit(decision_id: int) -> dict:
    """Start the real timing audit: one Tiger fork, five shifts replayed on the Vultr workers."""
    src, _ = source()
    running = [k for k, j in _JOBS.items() if not j.done]
    if running:
        if running[0] == decision_id:
            return _fork_status(decision_id, _JOBS[decision_id])
        raise HTTPException(409, f"an audit for decision {running[0]} is still running (one fork slot)")
    with _LOCK:
        d = _decision(src, decision_id)
        _JOB_ACTIONS[decision_id] = d.action
        _JOBS[decision_id] = src.start_fork_audit(decision_id)
    return _fork_status(decision_id, _JOBS[decision_id])


@app.get("/api/decisions/{decision_id}/fork-audit")
def fork_audit_status(decision_id: int) -> dict:
    job = _JOBS.get(decision_id)
    if job is None:
        raise HTTPException(404, f"no fork audit started for decision {decision_id}")
    return _fork_status(decision_id, job)


@app.get("/api/replay")
def replay() -> dict:
    src, _ = source()
    with _LOCK:
        week = src.replay_week()
    return {"rows": records(week, ["ts", "actual", "p10", "p50", "p90", "mw", "soc_mwh", "cum_pnl_gbp"])}


@app.get("/api/honesty")
def honesty() -> dict:
    src, _ = source()
    with _LOCK:
        summary = src.backtest_summary()
        regime = src.backtest_by_regime()
        cal = src.calibration()
        weak = src.weak_points()
        weeks = src.backtest_weeks()
        grade = src.self_grade()
    sentence = None
    if cal is not None and not cal.empty and cal.attrs.get("n"):
        sentence = calibration_sentence(int(cal.attrs["n"]), float(cal.attrs["coverage_p10_p90"]))
    return {
        "summary": records(summary),
        "by_regime": records(regime),
        "calibration": records(cal),
        "calibration_sentence": sentence,
        "weak_points": weak or [],
        "weeks": weeks,
        "self_grade": {k: _clean(v) for k, v in (grade or {}).items()},
        "captured_pct": _main_pct(summary),
    }
