"""Export the data the pitch site (pitch/) draws, as small JSON files in pitch/data/.

Owner: Ayo. Read-only against TEMPO_DATABASE_URL. The site is a static export, so these files are the
snapshot it ships with; re-run before a rehearsal to refresh them.

    python scripts/export_pitch.py            # all chapters
    python scripts/export_pitch.py hook       # one chapter
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tempo.db.conn import get_conn

OUT = Path(__file__).resolve().parents[1] / "pitch" / "data"
LONDON = ZoneInfo("Europe/London")

HOOK_DAY = date(2026, 3, 25)
HOOK_WINDOW = 4  # half-hours to fill or empty the 2 MWh battery at 1 MW
HOOK_NOW = "02:00"  # where the "now" line drops in
RANGE_DAYS = 28  # the uncertain band: p10-p90 of the same half-hour over the previous 4 weeks
BACKTEST_RUN = "db-20261024T202144Z"  # the 100-week walk-forward run quoted in docs/description.md


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=LONDON)
    return start, start + timedelta(days=1)


def _best_windows(prices: list[float], n: int) -> tuple[int, int]:
    """Start index of the dearest n-period window, and of the cheapest n-period window that ends before it."""
    avg = [sum(prices[i : i + n]) / n for i in range(len(prices) - n + 1)]
    sell = max(range(len(avg)), key=avg.__getitem__)
    buy = min(range(sell - n + 1), key=avg.__getitem__)
    return buy, sell


def hook(conn) -> dict:
    start, end = _day_bounds(HOOK_DAY)
    prices = pd.DataFrame(
        conn.execute(
            "SELECT bucket, price FROM prices_hh WHERE bucket >= %s AND bucket < %s ORDER BY bucket",
            (start, end),
        ).fetchall(),
        columns=["bucket", "price"],
    )
    if len(prices) != 48 or prices.price.isna().any():
        raise SystemExit(f"{HOOK_DAY}: expected 48 priced periods, got {prices.price.notna().sum()}")

    # Wind as a share of generation, per half-hour, to say why the night is cheap.
    mix = pd.DataFrame(
        conn.execute(
            """SELECT start_time, sum(value) FILTER (WHERE series = 'WIND') AS wind, sum(value) AS total
               FROM (SELECT DISTINCT ON (start_time, series) start_time, series, value FROM grid_raw
                     WHERE dataset = 'FUELHH' AND start_time >= %s AND start_time < %s
                     ORDER BY start_time, series, available_at DESC) latest
               GROUP BY 1 ORDER BY 1""",
            (start, end),
        ).fetchall(),
        columns=["bucket", "wind", "total"],
    )
    wind_share = dict(zip(mix.bucket, mix.wind / mix.total, strict=True))

    # Same half-hour over the previous four weeks, for the "you don't know tonight's price" band.
    hist = pd.DataFrame(
        conn.execute(
            "SELECT bucket, price FROM prices_hh WHERE bucket >= %s AND bucket < %s AND price IS NOT NULL",
            (start - timedelta(days=RANGE_DAYS), start),
        ).fetchall(),
        columns=["bucket", "price"],
    )
    hist["slot"] = [b.astimezone(LONDON).strftime("%H:%M") for b in hist.bucket]
    band = hist.groupby("slot").price.quantile([0.1, 0.9]).unstack()

    p = prices.price.round(2).tolist()
    buy, sell = _best_windows(p, HOOK_WINDOW)
    lo = min(range(48), key=p.__getitem__)
    hi = max(range(48), key=p.__getitem__)
    periods = []
    for i, row in prices.iterrows():
        t = row.bucket.astimezone(LONDON).strftime("%H:%M")
        ws = wind_share.get(row.bucket)
        periods.append(
            {
                "t": t,
                "price": p[i],
                "wind_share": None if ws is None else round(float(ws), 3),
                "range_lo": round(float(band.loc[t, 0.1]), 2),
                "range_hi": round(float(band.loc[t, 0.9]), 2),
            }
        )
    tempo = conn.execute(
        """SELECT count(*), sum(pnl_gbp), sum(perfect_pnl_gbp), count(*) FILTER (WHERE pnl_gbp < 0)
           FROM backtest_results WHERE run_id = %s AND strategy = 'tempo'""",
        (BACKTEST_RUN,),
    ).fetchone()
    weeks, pnl, perfect, losing = tempo
    buy_avg = sum(p[buy : buy + HOOK_WINDOW]) / HOOK_WINDOW
    sell_avg = sum(p[sell : sell + HOOK_WINDOW]) / HOOK_WINDOW
    return {
        "day": HOOK_DAY.isoformat(),
        "source": "APX MID price (prices_hh); wind share from FUELHH",
        "periods": periods,
        "low": {"i": lo, "t": periods[lo]["t"], "price": p[lo]},
        "high": {"i": hi, "t": periods[hi]["t"], "price": p[hi]},
        "charge": {"from": buy, "to": buy + HOOK_WINDOW - 1, "avg": round(buy_avg, 2)},
        "sell": {"from": sell, "to": sell + HOOK_WINDOW - 1, "avg": round(sell_avg, 2)},
        "spread": round(sell_avg - buy_avg, 2),
        "now": HOOK_NOW,
        "range_days": RANGE_DAYS,
        "headline": {
            "run_id": BACKTEST_RUN,
            "weeks": weeks,
            "pct_of_perfect": round(100 * pnl / perfect, 1),
            "pnl_gbp": round(pnl),
            "losing_weeks": losing,
        },
    }


DATA_DAY = date(2026, 10, 22)  # the day chapters 02 and 03 use
DATA_FROM, DATA_TO = 6, 24  # timeline window, hours of DATA_DAY (London)
DATA_TARGET = "19:00"  # the evening peak whose forecasts the timeline tracks
DATA_DECISION = "18:00"  # where the draggable decision line starts
TRAINING = Path(__file__).resolve().parents[1] / "models" / "training.json"


def data(conn) -> dict:
    from tempo.config import settings
    from tempo.db.stats import storage_stats

    st = storage_stats(conn)
    first, datasets = conn.execute("SELECT min(start_time), count(DISTINCT dataset) FROM grid_raw").fetchone()
    hh, daily, weekly = (
        conn.execute(f"SELECT count(*) FROM {v}").fetchone()[0]
        for v in ("prices_hh", "prices_daily", "prices_weekly")
    )  # noqa: S608
    decisions, holds = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE action = 'hold') FROM decisions WHERE run_id = 'live'"
    ).fetchone()
    training = json.loads(TRAINING.read_text())

    day, _ = _day_bounds(DATA_DAY)
    lo, hi = day + timedelta(hours=DATA_FROM), day + timedelta(hours=DATA_TO)
    hh_, mm_ = map(int, DATA_TARGET.split(":"))
    target = day + timedelta(hours=hh_, minutes=mm_)
    hm = lambda t: t.astimezone(LONDON).strftime("%H:%M")  # noqa: E731

    price = conn.execute(
        """SELECT start_time, available_at, value FROM grid_raw
           WHERE dataset = 'MID' AND series = 'APXMIDP' AND available_at >= %s AND available_at < %s
           ORDER BY available_at""",
        (lo, hi),
    ).fetchall()

    def forecasts(dataset: str, series: str) -> list[dict]:
        # Every publication in the window, with what it said about the target half-hour (if it covered it).
        rows = conn.execute(
            """SELECT available_at, max(value) FILTER (WHERE start_time = %s)
               FROM grid_raw WHERE dataset = %s AND series = %s AND available_at >= %s AND available_at < %s
               GROUP BY 1 ORDER BY 1""",
            (target, dataset, series, lo - timedelta(hours=6), hi),
        ).fetchall()
        out = [{"pub": hm(a), "value": v} for a, v in rows if a >= lo]
        before = [{"pub": hm(a), "value": v} for a, v in rows if a < lo and v is not None]
        return before[-1:] + out  # the last one before the window, so the panel is never empty

    return {
        "pipeline": {
            "history_from": first.astimezone(LONDON).date().isoformat(),
            "datasets": datasets,
            "rows": st["rows"],
            "pct_compressed": round(st["pct_saved"], 1),
            "chunks": st["total_chunks"],
            "hh": hh,
            "daily": daily,
            "weekly": weekly,
            "features": len(training["features"]),
            "train_seconds": training["seconds"],
            "decisions": decisions,
            "holds": holds,
        },
        "timeline": {
            "day": DATA_DAY.isoformat(),
            "from": f"{DATA_FROM:02d}:00",
            "to": f"{DATA_TO:02d}:00",
            "target": DATA_TARGET,
            "decision": DATA_DECISION,
            "mid_delay_min": settings().mid_availability_delay_min,
            "price": [{"pub": hm(a), "period": hm(s), "value": round(v, 2)} for s, a, v in price],
            "wind": forecasts("WINDFOR", ""),
            "demand": forecasts("NDF", "N"),
        },
    }


PRED_DECIDED = datetime(2026, 10, 22, 1, 0, tzinfo=LONDON)  # a typical live run, not the best (SPEC.md, 02)
MODEL_P50 = TRAINING.parent / "lgbm_p50.joblib"
FEATURE_NAMES = {  # plain English for the importance bars
    "demand_fc": "National demand forecast",
    "wind_share_fc": "Wind share of demand",
    "price_lag_1d": "Price this time yesterday",
    "price_lag_7d": "Price this time last week",
    "hour": "Hour of day",
    "wind_fc": "Wind forecast",
    "weekly_std": "Last week’s volatility",
    "daily_spread_lag_1d": "Yesterday’s spread",
    "dow": "Day of week",
    "weekly_mean": "Last week’s average",
}


def prediction(conn) -> dict:
    import joblib

    rows = conn.execute(
        """SELECT f.target_time, f.p10, f.p50, f.p90, a.price, y.price
           FROM forecasts f
           LEFT JOIN prices_hh a ON a.bucket = f.target_time
           LEFT JOIN prices_hh y ON y.bucket = f.target_time - interval '1 day'
           WHERE f.run_id = 'live' AND f.decided_at = %s ORDER BY f.target_time""",
        (PRED_DECIDED,),
    ).fetchall()
    if len(rows) != 48 or any(r[4] is None or r[5] is None for r in rows):
        raise SystemExit(
            f"{PRED_DECIDED}: expected 48 settled forecasts with yesterday's price, got {len(rows)}"
        )
    periods = [
        {
            "t": t.astimezone(LONDON).strftime("%H:%M"),
            "p10": round(a, 2),
            "p50": round(b, 2),
            "p90": round(c, 2),
            "actual": round(d, 2),
            "yesterday": round(e, 2),
        }
        for t, a, b, c, d, e in rows
    ]
    mae = lambda k: sum(abs(p[k] - p["actual"]) for p in periods) / len(periods)  # noqa: E731

    training = json.loads(TRAINING.read_text())
    model = joblib.load(MODEL_P50)
    booster = getattr(model, "booster_", model)
    gain = booster.feature_importance("gain")
    total = float(sum(gain))
    ranked = sorted(zip(training["features"], gain, strict=True), key=lambda x: -x[1])
    holdout = training["holdout"]
    return {
        "decided_at": PRED_DECIDED.strftime("%Y-%m-%d %H:%M"),
        "periods": periods,
        "day": {"lgbm_mae": round(mae("p50"), 1), "persistence_mae": round(mae("yesterday"), 1)},
        "holdout": {
            "rows": holdout["holdout_rows"],
            "lgbm_mae": round(holdout["p50_mae"], 1),
            "persistence_mae": round(holdout["persistence_mae"], 1),
            "pct_better": round(100 * (1 - holdout["p50_mae"] / holdout["persistence_mae"]), 1),
        },
        "features": [
            {"name": f, "label": FEATURE_NAMES.get(f, f), "pct": round(100 * g / total, 1)}
            for f, g in ranked[:5]
        ],
        "feature_count": len(training["features"]),
    }


# The next morning's live run. On 22 Oct the costs never change the schedule; here the cost gate decides:
# the overnight cycle is held, and lowering the wear brings it back (SPEC.md, 03).
DECISION_DECIDED = datetime(2026, 10, 23, 7, 0, tzinfo=LONDON)
DECISION_HOLD_AT = "04:00"  # decision 1386: buy 04:00, sell 07:00, spread 18.75 <= cost 22.82
WHATIF_WEAR = list(range(0, 31))  # £ per MWh delivered (cycle cost / capacity); the live setting is 10
WHATIF_EFF = [75, 80, 85, 90, 95]  # round-trip efficiency %, live 90

_GATE = (
    r"spread (?P<spread>[\d.-]+) (?P<op><=|>) cost (?P<cost>[\d.-]+) "
    r"\(efficiency loss (?P<loss>[\d.-]+) at \d+% \+ degradation (?P<deg>[\d.-]+)/MWh\)"
)


def _plain_reason(reason: str, local: dict[str, str], p: dict[str, float], eff: float) -> dict:
    """The optimiser's reason string, made readable: times in UK time (greedy.py prints UTC), plain words.

    Raises on any string it doesn't recognise, so the site never shows a reason it can't explain.
    """
    import re

    def gate(m):
        return {k: float(m[k]) for k in ("spread", "cost", "loss", "deg")}

    if m := re.fullmatch(rf"charge for sale at (?P<t>\d\d:\d\d): {_GATE}", reason):
        t = local[m["t"]]
        return {"kind": "charge", "text": f"Buy now to sell at {t} (£{p[t]:.2f}).", "partner": t, **gate(m)}
    if m := re.fullmatch(rf"sell energy bought at (?P<t>\d\d:\d\d): {_GATE}", reason):
        t = local[m["t"]]
        return {
            "kind": "sell",
            "text": f"Sell the energy bought at {t} (£{p[t]:.2f}).",
            "partner": t,
            **gate(m),
        }
    if m := re.fullmatch(
        r"sell stored energy: price (?P<price>[\d.-]+) > wear (?P<wear>[\d.-]+)/MWh", reason
    ):
        return {
            "kind": "sell",
            "text": f"Sell energy already in the battery: £{float(m['price']):.2f} beats the wear of "
            f"£{float(m['wear']):.2f}/MWh.",
        }
    if m := re.fullmatch(rf"hold: {_GATE}", reason):
        g = gate(m)
        sell = g["loss"] / (1 - eff)  # cost_gate: loss = (1 - eff) * sell price
        buy = sell - g["spread"]
        near = lambda v: min(p, key=lambda t: abs(p[t] - v))  # noqa: E731
        return {
            "kind": "hold-gate",
            "text": "Its best trade doesn\u2019t cover the costs of a cycle.",
            "buy_t": near(buy),
            "sell_t": near(sell),
            "buy": round(buy, 2),
            "sell": round(sell, 2),
            **g,
        }
    if m := re.fullmatch(
        r"hold: battery full between (?P<a>\d\d:\d\d) and (?P<b>\d\d:\d\d) \(SoC .*\)", reason
    ):
        a, b = local[m["a"]], local[m["b"]]
        return {
            "kind": "hold-full",
            "text": f"Its best trade (buy {a}, sell {b}) needs room the battery doesn\u2019t have: it is "
            "already full in between, with energy for dearer half-hours.",
        }
    if reason.startswith("hold: better-paying periods"):
        return {"kind": "hold-busy", "text": "Dearer half-hours nearby already use the battery\u2019s power."}
    if reason == "hold: no other free period in the horizon to pair with":
        return {"kind": "hold-none", "text": "Nothing left in the next 24 hours to trade against."}
    raise SystemExit(f"unrecognised optimiser reason: {reason!r}")


def decision(conn) -> dict:
    import numpy as np

    from tempo.decide.engine import battery_from_settings, current_soc
    from tempo.optimise.greedy import GreedyOptimiser
    from tempo.sim.battery import simulate

    q = pd.DataFrame(
        conn.execute(
            """SELECT f.target_time, f.p10, f.p50, f.p90, a.price FROM forecasts f
               LEFT JOIN prices_hh a ON a.bucket = f.target_time
               WHERE f.run_id = 'live' AND f.decided_at = %s ORDER BY 1""",
            (DECISION_DECIDED,),
        ).fetchall(),
        columns=["t", "p10", "p50", "p90", "actual"],
    ).set_index("t")
    stored = pd.DataFrame(
        conn.execute(
            "SELECT target_time, decision_id, action, mw, reason FROM decisions "
            "WHERE run_id = 'live' AND decided_at = %s ORDER BY 1",
            (DECISION_DECIDED,),
        ).fetchall(),
        columns=["t", "id", "action", "mw", "reason"],
    ).set_index("t")
    battery = battery_from_settings(current_soc(conn, "live", DECISION_DECIDED, default=None) or None)
    live = GreedyOptimiser().plan(q, battery)
    if not np.allclose(live.mw.to_numpy(), stored.mw.to_numpy(), atol=1e-6):
        raise SystemExit("re-running the optimiser no longer reproduces the stored live decisions")

    local = {t.strftime("%H:%M"): t.astimezone(LONDON).strftime("%H:%M") for t in q.index.tz_convert("UTC")}
    p50 = {t.astimezone(LONDON).strftime("%H:%M"): float(v) for t, v in q.p50.items()}
    sim = simulate(battery, live.mw.to_numpy(), q.p50.to_numpy())
    periods = []
    for k, (t, row) in enumerate(stored.iterrows()):
        periods.append(
            {
                "t": t.astimezone(LONDON).strftime("%H:%M"),
                "id": int(row.id),
                "p50": round(float(q.p50.iloc[k]), 2),
                "actual": None if pd.isna(q.actual.iloc[k]) else round(float(q.actual.iloc[k]), 2),
                "action": row.action,
                "mw": round(float(row.mw), 3),
                "soc": round(float(sim.soc_path[k]), 3),
                "why": _plain_reason(row.reason, local, p50, battery.rt_efficiency),
            }
        )
    hold = next(p for p in periods if p["t"] == DECISION_HOLD_AT and p["why"]["kind"] == "hold-gate")

    def run(wear: float, eff: float) -> dict:
        b = battery_from_settings(battery.soc_mwh)
        b.cycle_cost_gbp, b.rt_efficiency = wear * b.capacity_mwh, eff / 100
        plan = GreedyOptimiser().plan(q, b)
        mw = plan.mw.to_numpy()
        exp = simulate(b, mw, q.p50.to_numpy())
        code = "".join({"charge": "c", "discharge": "s", "hold": "h"}[a] for a in plan.action)
        return {
            "a": code,
            "soc": [round(float(v), 3) for v in exp.soc_path],
            "trades": int((plan.action != "hold").sum()),
            "expected": round(exp.pnl_gbp, 2),
        }

    grid = {f"{w}_{e}": run(w, e) for w in WHATIF_WEAR for e in WHATIF_EFF}
    return {
        "decided_at": DECISION_DECIDED.strftime("%Y-%m-%d %H:%M"),
        "battery": {
            "capacity_mwh": battery.capacity_mwh,
            "power_mw": battery.power_mw,
            "rt_efficiency": battery.rt_efficiency,
            "wear_per_mwh": battery.cycle_cost_gbp / battery.capacity_mwh,
            "start_soc": battery.soc_mwh,
        },
        "periods": periods,
        "expected_pnl": round(sim.pnl_gbp, 2),
        "hold": hold,
        "whatif": {"wear": WHATIF_WEAR, "eff": WHATIF_EFF, "grid": grid},
    }


STRATEGIES = [  # ladder order, worst to best
    ("simple_rule", "Simple rule", "charge 1–5am, sell 5–7pm"),
    ("persistence_greedy", "Same as yesterday", "persistence forecast + our optimiser"),
    ("tempo", "Tempo", "LightGBM + greedy · what runs live"),
    ("tempo_lp", "Tempo LP", "LightGBM + linear program"),
    ("perfect", "Perfect foresight", "knows every price in advance"),
]
REPLAY = TRAINING.parent / "replay_week.parquet"


def proof(conn) -> dict:
    from tempo.backtest.replay import per_period_pnl
    from tempo.decide.engine import battery_from_settings
    from tempo.optimise.perfect import perfect_foresight

    ladder = []
    for key, name, sub in STRATEGIES:
        n, pnl, perfect, lo, hi, losing = conn.execute(
            """SELECT count(*), sum(pnl_gbp), sum(perfect_pnl_gbp), min(pct_of_perfect), max(pct_of_perfect),
                      count(*) FILTER (WHERE pnl_gbp < 0)
               FROM backtest_results WHERE run_id = %s AND strategy = %s""",
            (BACKTEST_RUN, key),
        ).fetchone()
        ladder.append(
            {
                "key": key,
                "name": name,
                "sub": sub,
                "weeks": n,
                "pnl": round(pnl),
                "pct": round(100 * pnl / perfect, 1),
                "worst": round(lo, 1),
                "best": round(hi, 1),
                "losing": losing,
            }
        )
    weeks = [
        {"week": w.isoformat(), "pct": round(p, 1), "regime": r, "pnl": round(g, 2)}
        for w, p, r, g in conn.execute(
            "SELECT week_start, pct_of_perfect, regime, pnl_gbp FROM backtest_results "
            "WHERE run_id = %s AND strategy = 'tempo' ORDER BY 1",
            (BACKTEST_RUN,),
        ).fetchall()
    ]

    meta = json.loads(REPLAY.with_suffix(".json").read_text())
    rp = pd.read_parquet(REPLAY)
    battery = battery_from_settings()
    best_mw = perfect_foresight(rp.actual.to_numpy(), battery).mw.to_numpy()
    _, best_pnl = per_period_pnl(battery, best_mw, rp.actual.to_numpy())
    perfect_cum = best_pnl.cumsum()
    week_perfect = conn.execute(
        "SELECT perfect_pnl_gbp FROM backtest_results "
        "WHERE run_id = %s AND strategy = 'tempo' AND week_start = %s",
        (BACKTEST_RUN, meta["week_start"]),
    ).fetchone()[0]
    if abs(perfect_cum[-1] - week_perfect) > 0.05 or abs(rp.cum_pnl_gbp.iloc[-1] - meta["pnl_gbp"]) > 0.05:
        raise SystemExit("replay week no longer matches the backtest totals")
    replay = [
        {
            "t": r.ts.tz_convert(LONDON).strftime("%a %H:%M"),
            "actual": round(r.actual, 2),
            "p50": round(r.p50, 2),
            "mw": round(r.mw, 3),
            "soc": round(max(r.soc_mwh, 0.0), 3),
            "cum": round(r.cum_pnl_gbp, 2),
            "perfect": round(float(perfect_cum[k]), 2),
        }
        for k, r in enumerate(rp.itertuples())
    ]
    return {
        "run_id": BACKTEST_RUN,
        "ladder": ladder,
        "weeks": weeks,
        "replay": {
            **{k: meta[k] for k in ("week_start", "regime", "pct_of_perfect", "pnl_gbp", "chosen_as")},
            "perfect_gbp": round(week_perfect, 2),
            "periods": replay,
        },
    }


TIMING_DECISION = 1353  # the 11:30 charge in the 23 Oct 07:00 plan (chapter 03); demo_reset may pick another
SHIFT_LABELS = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}


def timing(conn) -> dict:
    from datetime import UTC

    from tempo.audit.selfgrade import self_grade

    decided, target, action, mw, reason = conn.execute(
        "SELECT decided_at, target_time, action, mw, reason FROM decisions WHERE decision_id = %s",
        (TIMING_DECISION,),
    ).fetchone()
    batch = conn.execute(
        "SELECT f.target_time, f.p50 FROM forecasts f WHERE f.run_id = 'live' AND f.decided_at = %s",
        (decided,),
    ).fetchall()
    local = {t.astimezone(UTC).strftime("%H:%M"): t.astimezone(LONDON).strftime("%H:%M") for t, _ in batch}
    p50 = {t.astimezone(LONDON).strftime("%H:%M"): float(v) for t, v in batch}

    started = conn.execute(
        "SELECT max(started_at) FROM audits WHERE decision_id = %s AND mode = 'fork'", (TIMING_DECISION,)
    ).fetchone()[0]
    rows = conn.execute(
        """SELECT shift, pnl_gbp, pnl_delta_gbp, worker_id, fork_service_id, started_at, finished_at
           FROM audits
           WHERE decision_id = %s AND mode = 'fork' AND started_at >= %s - interval '2 minutes'
           ORDER BY shift""",
        (TIMING_DECISION, started),
    ).fetchall()
    if len(rows) != 5 or any(r[1] is None for r in rows):
        raise SystemExit(f"decision {TIMING_DECISION}: the last fork audit is incomplete ({len(rows)} rows)")
    grade = self_grade(conn, since=datetime.now(UTC) - timedelta(days=30))
    return {
        "decision": {
            "id": TIMING_DECISION,
            "decided_at": decided.astimezone(LONDON).strftime("%a %d %b %H:%M"),
            "target": target.astimezone(LONDON).strftime("%H:%M"),
            "day": target.astimezone(LONDON).strftime("%a %d %b"),
            "action": action,
            "mw": round(mw, 2),
            "why": _plain_reason(reason, local, p50, 0.9),
        },
        "recorded": {
            "started_at": started.astimezone(LONDON).strftime("%a %d %b %H:%M"),
            "elapsed_s": round((max(r[6] for r in rows) - min(r[5] for r in rows)).total_seconds(), 1),
            "rows": [
                {
                    "shift": sh,
                    "label": SHIFT_LABELS[sh],
                    "pnl_gbp": round(pnl, 2),
                    "pnl_delta_gbp": round(d, 2),
                    "worker_id": w,
                    "forked": f is not None,
                }
                for sh, pnl, d, w, f, *_ in rows
            ],
        },
        "self_grade": {
            "n_cycles": grade["n_cycles"],
            "within_one": round(grade["pct_within_one_period"] * grade["n_cycles"]),
            "pct_within_one": round(100 * grade["pct_within_one_period"], 1),
            "mean_cost_gbp": round(grade["mean_cost_of_mistiming_gbp"], 2),
        },
    }


CHAPTERS = {
    "hook": hook,
    "data": data,
    "prediction": prediction,
    "decision": decision,
    "proof": proof,
    "timing": timing,
}


def main(names: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        for name in names or CHAPTERS:
            data = CHAPTERS[name](conn)
            path = OUT / f"{name}.json"
            path.write_text(json.dumps(data, indent=1) + "\n")
            print(f"wrote {path.relative_to(OUT.parents[1])}")


if __name__ == "__main__":
    main(sys.argv[1:])
