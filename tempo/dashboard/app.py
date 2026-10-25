"""Streamlit app: the Tempo dashboard as one page in the style of grid.iamkate.com (National Grid: Live).

Owner: Ayo. See docs/ayo.md and docs/ui-plan.md. Run with `make dashboard` or
`streamlit run tempo/dashboard/app.py`.

Top to bottom: a centred title, two KPI panels (time / price / next action, and the honesty equation), the
plan wheel (today's 48 settlement periods on a 24-hour clock with the forecast price ring inside, the plan's
blocks tabled on the left and the market and battery on the right), then one panel per demo section: Live,
Replay, Timing audit, Honesty, About. Each panel opens with a sentence built from real numbers. With
TEMPO_DATABASE_URL set every section reads `DbSource`; a query that hits a missing or empty table falls
back to synthetic data and says so in a note under that section. The Timing audit button takes a Tiger fork
and replays on the Vultr pool in a background job (fork mode), or replays in-process (the on-stage fallback).
"""

from __future__ import annotations

from datetime import UTC, datetime

import altair as alt
import pandas as pd
import streamlit as st

from tempo.config import settings
from tempo.dashboard import jobs, ui
from tempo.dashboard import theme as T
from tempo.dashboard.data import (
    HEADLINE_STRATEGY,
    SHIFTS,
    STRATEGY_LABELS,
    calibration_sentence,
    current_settlement_period,
    pick_source,
)

st.set_page_config(page_title="Tempo: Live", page_icon="⚡", layout="wide")

SHIFT_LABELS = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}
STATE_ICON = {"queued": "○", "forking": "◌", "ready": "◍", "replaying": "◉", "done": "✓", "failed": "✗"}
MODE_INPROCESS, MODE_FORK = "in-process", "Tiger fork + Vultr workers"
SECTIONS = [
    ("live", "Live"),
    ("replay", "Replay"),
    ("audit", "Timing audit"),
    ("honesty", "Honesty"),
    ("about", "About"),
]
REPO_URL = "https://github.com/ernqiteng/OxHack26"


@st.cache_resource
def get_source():
    return pick_source(settings().database_url)


@st.cache_data(ttl=60, show_spinner=False)
def worker_health() -> tuple[int, int, str] | None:
    """(healthy, total, kind) for the status pill; None when no pool can be found. Cached 60 s."""
    import asyncio

    try:
        from tempo.audit.pool import default_pool

        pool, _ = default_pool()
        health = asyncio.run(pool.health(timeout=3))
        return sum(ok for ok, _ in health.values()), len(health), getattr(pool, "kind", "http")
    except Exception:  # noqa: BLE001 - a dot, not a page, depends on this
        return None


def show_notes(src, *methods: str) -> None:
    for m in methods:
        note = src.notes.get(m)
        if note:
            st.warning(f"{m}: {note}", icon="⚠️")


def main_strategy_row(summary: pd.DataFrame):
    """The honesty number: Tempo's row if present, else the best non-perfect row."""
    rows = summary[~summary.strategy.str.lower().str.startswith("perfect")]
    if rows.empty:
        return None
    live = rows[rows.strategy == STRATEGY_LABELS[HEADLINE_STRATEGY]]
    if not live.empty:
        return live.iloc[0]
    tempo = rows[rows.strategy.str.lower().str.startswith("tempo")]
    return (tempo if not tempo.empty else rows.sort_values("pct_of_perfect")).iloc[-1]


def perfect_row(summary: pd.DataFrame):
    rows = summary[summary.strategy.str.lower().str.startswith("perfect")]
    return None if rows.empty else rows.iloc[0]


def live_snapshot(src, now: datetime) -> dict:
    """Everything the header, the wheel and the Live panel share, fetched once per render."""
    midnight, period = current_settlement_period(now)
    prices = src.recent_prices(24)
    fc = src.next_forecast()
    sched = src.todays_schedule()
    upcoming = sched[(sched.action != "hold")] if not sched.empty else sched
    if not sched.empty and not upcoming.empty:
        nxt = upcoming.iloc[0]
        glyph = T.ACTION_GLYPH.get(nxt.action, "")
        label = T.ACTION_LABEL.get(nxt.action, nxt.action)
        when = T.local_naive(nxt.target_time)
        wait = (pd.Timestamp(nxt.target_time) - pd.Timestamp(now)).total_seconds() / 3600
        next_short = f"{glyph} {label} {abs(nxt.mw):.0f} MW"
        next_text = f"{next_short} at {when:%H:%M}"
        next_sub = f"{when:%H:%M} · in {wait:.1f} h" if wait >= 0.05 else f"{when:%H:%M} · now"
    else:
        next_short, next_text, next_sub = "—", "no live schedule yet", "waiting for the decision engine"
    latest = prices.iloc[-1] if not prices.empty else None
    return {
        "now": now,
        "midnight": midnight,
        "period": period,
        "prices": prices,
        "fc": fc,
        "sched": sched,
        "next_short": next_short,
        "next_text": next_text,
        "next_sub": next_sub,
        "latest_price": None if latest is None else float(latest.price),
        "spread": float(fc.p50.max() - fc.p50.min()) if not fc.empty else None,
    }


# ---------------------------------------------------------------------------------------------
# Header: title, nav, the two KPI panels
# ---------------------------------------------------------------------------------------------


@st.fragment(run_every="30s")
def header_strip() -> None:
    src, note = get_source()
    now = datetime.now(tz=UTC)
    snap = live_snapshot(src, now)
    now_local = T.local_naive(now)
    summary = src.backtest_summary()
    main = main_strategy_row(summary)
    perfect = perfect_row(summary)
    weeks = src.backtest_weeks()

    health = worker_health()
    synthetic = bool(src.notes) or src.name == "synthetic"
    tiger = "Tiger: connected" if src.name != "synthetic" else "Tiger: not connected"
    pills: list[tuple[bool | None, str]] = [(src.name != "synthetic", tiger)]
    if health is None:
        pills.append((False, "workers: none"))
    else:
        ok, total, kind = health
        kind_label = "Vultr " if kind == "http" else "local "
        pills.append((ok == total and total > 0, f"{ok}/{total} {kind_label}workers"))
    pills.append((None if synthetic else True, "synthetic data in use" if synthetic else "all data live"))

    with st.container(key="hero"):
        ui.top_line(
            f'A project by Ayo, Ernqi and Girik · <a href="{REPO_URL}">OxHack 2026, theme TIME</a>', pills
        )
        st.title("Tempo: Live")
        honesty = ""
        if main is not None:
            name = main.strategy.split(" (")[0]
            honesty = (
                f" [{name} captures {main.pct_of_perfect:.1f}% of perfect foresight"
                + (f" over {weeks} unseen weeks" if weeks else "")
                + "](#honesty)."
            )
        st.markdown(
            "Tempo decides when a 2 MWh grid battery charges, sells or holds on Great Britain's half-hourly "
            "market, then proves whether each decision was made at the right moment." + honesty
        )
        st.caption(
            f"{snap['midnight']:%A %d %B %Y} · settlement period {snap['period']} · {now_local:%H:%M} UK"
        )
        ui.nav_tabs(SECTIONS)

    left, right = st.columns(2)
    with left:
        ui.kpi_panel(
            [
                {
                    "label": "Time",
                    "value": f"{now_local:%H:%M}",
                    "unit": " UK",
                    "help": "UK clock time. Settlement periods are defined in local time, 48 a day.",
                },
                {
                    "label": "Period",
                    "value": str(snap["period"]),
                    "unit": " / 48",
                    "help": "The current half-hour settlement period (46 or 50 on clock-change days).",
                },
                {
                    "label": "Price",
                    "value": "—" if snap["latest_price"] is None else f"£{snap['latest_price']:,.2f}",
                    "unit": "/MWh",
                    "help": "Latest APX MID (market index) price from Elexon, available period end + 10 min.",
                },
                {
                    "label": "Next action",
                    "value": snap["next_short"],
                    "help": "The next charge or sell in the live 48-period plan. Holds are on the wheel.",
                },
            ]
        )
    with right:
        if main is not None and perfect is not None:
            name = main.strategy.split(" (")[0]
            ui.kpi_panel(
                [
                    {
                        "label": "Captured",
                        "value": f"{main.pct_of_perfect:.1f}",
                        "unit": "%",
                        "help": f"{name}'s profit as a share of perfect foresight over "
                        + (f"{weeks} unseen weeks" if weeks else "the walk-forward backtest")
                        + ". The honesty number.",
                    },
                    {
                        "label": name,
                        "value": f"£{main.pnl_gbp:,.0f}",
                        "help": main.strategy,
                    },
                    {
                        "label": "Perfect",
                        "value": f"£{perfect.pnl_gbp:,.0f}",
                        "help": "What the same battery would have made knowing every price in advance.",
                    },
                ],
                ops=["=", "÷"],
            )
        else:
            ui.kpi_panel([{"label": "Captured", "value": "—", "help": "No backtest results yet."}])


# ---------------------------------------------------------------------------------------------
# Live: the wheel, then the panel
# ---------------------------------------------------------------------------------------------


def plan_wheel_panel(src, snap: dict) -> None:
    now_local = T.local_naive(snap["now"])
    periods = ui.plan_periods(snap["sched"], snap["fc"])
    fc, prices = snap["fc"], snap["prices"]
    state = src.battery_state() or {}
    battery = settings().battery
    soc = state.get("soc_mwh")

    centre = {
        "title": f"Period {snap['period']} of 48",
        "value": snap["next_short"] if snap["next_short"] != "—" else "no plan yet",
        "sub": snap["next_sub"],
    }
    market: list[dict] = []
    if not prices.empty:
        p = prices.price.astype(float)
        market.append(
            {
                "name": "APX price",
                "help": "Last 24 h of half-hourly APX MID prices; the white line in Fig 1.1.",
                "aux": f"{T.local_naive(prices.bucket.iloc[-1]):%H:%M}",
                "value": ui.unit(f"£{p.iloc[-1]:,.2f}", "/MWh"),
                "spark": ui.spark(p, T.ACTUAL, title=f"24 h: £{p.min():.0f} to £{p.max():.0f}/MWh"),
            }
        )
    if not fc.empty:
        p50 = fc.p50.astype(float)
        cheap, dear = fc.iloc[int(p50.idxmin())], fc.iloc[int(p50.idxmax())]
        width = (fc.p90 - fc.p10).astype(float)
        market += [
            {
                "name": "Forecast p50",
                "help": "Median forecast for the next 24 h, from the LightGBM quantile model.",
                "aux": "mean",
                "value": ui.unit(f"£{p50.mean():,.0f}", "/MWh"),
                "spark": ui.spark(p50, T.BELIEF, title=f"p50: £{p50.min():.0f} to £{p50.max():.0f}/MWh"),
            },
            {
                "name": "Cheapest period",
                "help": "The period with the lowest median forecast: where a charge belongs.",
                "aux": f"{T.local_naive(cheap.target_time):%H:%M}",
                "value": ui.unit(f"£{cheap.p50:,.0f}", "/MWh"),
                "spark": "",
            },
            {
                "name": "Dearest period",
                "help": "The period with the highest median forecast: where a sell belongs.",
                "aux": f"{T.local_naive(dear.target_time):%H:%M}",
                "value": ui.unit(f"£{dear.p50:,.0f}", "/MWh"),
                "spark": "",
            },
            {
                "name": "Spread",
                "help": "Dearest minus cheapest p50. Below the cost of a round trip, the right call is hold.",
                "aux": "",
                "value": ui.unit(f"£{p50.max() - p50.min():,.0f}", "/MWh"),
                "spark": "",
            },
            {
                "name": "Band p10–p90",
                "help": "Width of the 80% forecast band, mean over the next 24 h. Wider means less sure.",
                "aux": "mean",
                "value": ui.unit(f"£{width.mean():,.0f}", "/MWh"),
                "spark": ui.spark(width, T.BELIEF, title="band width by horizon"),
            },
        ]
    battery_rows = [
        {
            "name": "State of charge",
            "help": "Latest battery_state row written by the live decision engine.",
            "aux": "—" if soc is None else f"{100 * soc / battery.capacity_mwh:.0f}%",
            "value": "—" if soc is None else ui.unit(f"{soc:.2f}", " MWh"),
            "spark": "" if soc is None else ui.meter(soc / battery.capacity_mwh, T.BRAND),
        },
        {
            "name": "Live P&L",
            "help": "Cumulative £ of the live run since it started trading"
            + ("" if not state.get("ts") else f", to {T.local_naive(state['ts']):%H:%M}")
            + ".",
            "aux": "",
            "value": "—" if state.get("cum_pnl_gbp") is None else ui.gbp(state["cum_pnl_gbp"]),
            "spark": "",
        },
        {
            "name": "Capacity",
            "help": "Battery size.",
            "aux": "",
            "value": ui.unit(f"{battery.capacity_mwh:g}", " MWh"),
            "spark": "",
        },
        {
            "name": "Power",
            "help": "The most it can charge or discharge in any period.",
            "aux": "",
            "value": ui.unit(f"{battery.power_mw:g}", " MW"),
            "spark": "",
        },
        {
            "name": "Round trip",
            "help": "Energy kept over a full charge and discharge.",
            "aux": "",
            "value": ui.unit(f"{100 * battery.rt_efficiency:.0f}", "%"),
            "spark": "",
        },
        {
            "name": "Cycle cost",
            "help": "Wear cost charged per MWh cycled; part of the hold threshold.",
            "aux": "",
            "value": ui.unit(f"£{battery.cycle_cost_gbp:g}", "/MWh"),
            "spark": "",
        },
    ]
    heads = {
        "market": "" if snap["latest_price"] is None else ui.unit(f"£{snap['latest_price']:,.2f}", "/MWh"),
        "battery": "" if soc is None else ui.unit(f"{soc:.2f}", " MWh"),
    }
    ui.plan_wheel(periods, now_local, centre, market, battery_rows, heads)


def section_live(src) -> None:
    now = datetime.now(tz=UTC)
    snap = live_snapshot(src, now)
    plan_wheel_panel(src, snap)
    hold = src.latest_hold()
    with ui.panel("live"):
        ui.section(
            "Live",
            f"{snap['midnight']:%A %d %B}, period {snap['period']} of 48: {snap['next_text']}.",
            "live",
            aside="last 24 h and the next 24 h",
        )
        ui.fig_label("1.1", "APX MID, last 24 h actual and next 24 h forecast with p10–p90 band")
        st.altair_chart(ui.price_chart(snap["prices"], snap["fc"], now, snap["sched"]), width="stretch")
        if snap["sched"].empty:
            st.info("No live decisions yet: the decision engine writes the first 48-period schedule.")
        if hold:
            ui.hold_card(hold)
        show_notes(src, "recent_prices", "next_forecast", "todays_schedule", "latest_hold", "battery_state")


# ---------------------------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------------------------


def section_replay(src) -> None:
    week = src.replay_week()
    n = len(week)
    upto = int(st.session_state.get("replay_upto", min(96, n)))
    shown = week.iloc[:upto]
    pnl = float(shown.cum_pnl_gbp.iloc[-1])
    # The week is cut on UTC days in the parquet; the last period (23:30 UTC) is already the next day in
    # UK time, so name the span by UTC dates, not local ones.
    first, last = (
        pd.Timestamp(week.ts.iloc[0]).tz_convert("UTC"),
        pd.Timestamp(week.ts.iloc[-1]).tz_convert("UTC"),
    )
    span = (
        f"{first.day} to {last.day} {last:%B %Y}"
        if first.month == last.month
        else f"{first.day} {first:%B} to {last.day} {last:%B %Y}"
    )
    with ui.panel("replay"):
        ui.section(
            "Replay",
            f"The windy week of {span}, played forward: {ui.gbp(pnl)} so far.",
            "replay",
            aside="one stored week, period by period",
        )
        st.slider("Periods played", min_value=1, max_value=n, value=min(96, n), step=1, key="replay_upto")
        playhead = week.ts.iloc[upto - 1]
        ui.fig_label("2.1", "Forecast band vs actual, with the playhead")
        actual = shown.rename(columns={"ts": "bucket", "actual": "price"})[["bucket", "price"]]
        fc = shown.rename(columns={"ts": "target_time"})[["target_time", "p10", "p50", "p90"]]
        st.altair_chart(ui.price_chart(actual, fc, playhead), width="stretch")
        c1, c2 = st.columns(2)
        soc = T.localise(shown[["ts", "soc_mwh"]], ["ts"])
        cum = T.localise(shown[["ts", "cum_pnl_gbp"]], ["ts"])
        with c1:
            ui.fig_label("2.2", "State of charge, MWh")
            st.altair_chart(
                alt.Chart(soc)
                .mark_area(color=T.CHARGE, opacity=0.35, line={"color": T.CHARGE})
                .encode(
                    x=T.time_axis("ts"), y=alt.Y("soc_mwh:Q", title="MWh", scale=alt.Scale(domain=[0, 2]))
                )
                .properties(height=T.SECONDARY_H),
                width="stretch",
            )
        with c2:
            ui.fig_label("2.3", "Cumulative £")
            st.altair_chart(
                alt.Chart(cum)
                .mark_line(color=T.BRAND, interpolate="step-after", strokeWidth=2)
                .encode(x=T.time_axis("ts"), y=alt.Y("cum_pnl_gbp:Q", title="£"))
                .properties(height=T.SECONDARY_H),
                width="stretch",
            )
        show_notes(src, "replay_week")


# ---------------------------------------------------------------------------------------------
# Timing audit
# ---------------------------------------------------------------------------------------------


def _store_result(job, src) -> None:
    """Move a finished job's rows into session_state so the result view renders without the job."""
    st.session_state["audit_result"] = job.rows
    st.session_state["audit_mode_used"] = "fork" if job.error is None else "fork (crashed)"
    st.session_state["audit_log"] = job.progress.log_lines()
    st.session_state["audit_error"] = job.error
    st.session_state["audit_elapsed"] = job.running_s
    if getattr(job, "note", None):
        src.notes["fork_audit"] = job.note
    st.session_state.pop("audit_job", None)


@st.fragment(run_every=0.5)
def audit_progress_view() -> None:
    """Re-renders every half second while a fork audit runs in the background."""
    job = st.session_state.get("audit_job")
    if job is None:
        return
    if job.done:
        _store_result(job, get_source()[0])
        st.rerun(scope="app")
        return
    states = job.states()
    cols = st.columns(len(SHIFTS))
    for col, shift in zip(cols, SHIFTS, strict=True):
        state = states.get(shift, "queued")
        with col, st.container(border=True):
            st.markdown(f"**{SHIFT_LABELS[shift]}**" if shift else f"**:green[{SHIFT_LABELS[shift]}]**")
            st.markdown(f"{STATE_ICON.get(state, '○')} {jobs.STATE_LABEL.get(state, state)}")
            st.caption(job.progress.workers.get(shift) or "")
    st.caption(f"elapsed {job.running_s:04.1f} s")
    st.code("\n".join(job.log_lines()) or "starting…", language="text")


def render_audit_result(src, rows: pd.DataFrame) -> None:
    cols = st.columns(len(SHIFTS))
    for col, shift in zip(cols, SHIFTS, strict=True):
        r = rows[rows["shift"] == shift].iloc[0]
        with col, st.container(border=True):
            st.markdown(f"**{SHIFT_LABELS[shift]}**" if shift else f"**:green[{SHIFT_LABELS[shift]}]**")
            st.metric(
                "PnL",
                ui.gbp(r.pnl_gbp),
                delta=None if pd.isna(r.pnl_delta_gbp) or shift == 0 else f"{r.pnl_delta_gbp:+.2f}",
            )
            worker = r.worker_id if isinstance(r.worker_id, str) and r.worker_id else "in-process"
            st.caption(worker)
    errors = [(r.shift, r.error) for r in rows.itertuples() if isinstance(getattr(r, "error", None), str)]
    for shift, err in errors:
        st.error(f"shift {shift:+d} failed: {err}")
    if st.session_state.get("audit_error"):
        st.error(f"audit crashed: {st.session_state['audit_error']}")
    c1, c2 = st.columns([3, 2])
    with c1:
        ui.fig_label("3.2", "Cost of mistiming, £ versus as decided")
        st.altair_chart(ui.delta_bars(rows), width="stretch")
    with c2:
        elapsed = st.session_state.get("audit_elapsed")
        if elapsed is None:
            elapsed = (rows.finished_at.max() - rows.started_at.min()).total_seconds()
        fork_ids = sorted({f for f in rows.get("fork_service_id", pd.Series(dtype=object)).dropna() if f})
        st.caption(
            f"mode: {st.session_state.get('audit_mode_used')}, total elapsed {elapsed:.1f} s, "
            f"simulator: {src.sim_name}" + (f", fork {', '.join(map(str, fork_ids))}" if fork_ids else "")
        )
        log = st.session_state.get("audit_log")
        if log:
            ui.fig_label("3.3", "Audit log")
            st.code("\n".join(log[-14:]), language="text")
    with st.expander("Rows written to audits"):
        st.dataframe(
            rows[["shift", "pnl_gbp", "pnl_delta_gbp", "mode", "worker_id", "fork_service_id"]],
            hide_index=True,
            width="stretch",
        )


def section_audit(src) -> None:
    decisions = src.recent_decisions()
    labels = {
        int(r.decision_id): f"#{r.decision_id}  {T.local_naive(r.decided_at):%d %b %H:%M}  {r.action}"
        + (f"  ({r.reason})" if r.reason else "")
        + ("  [rehearsal]" if getattr(r, "run_id", "live") == "selftest" else "")
        for r in decisions.itertuples()
    }
    job = st.session_state.get("audit_job")
    running = job is not None and not job.done
    rows = st.session_state.get("audit_result")
    sentence = jobs.hero_sentence(rows, st.session_state.get("audit_action")) if rows is not None else None
    with ui.panel("audit"):
        ui.section(
            "Timing audit",
            sentence or "Click a decision: one Tiger fork, five timelines, five Vultr workers.",
            "audit",
            aside="the same action, shifted −1 h to +1 h",
        )
        ui.fig_label("3.1", "Five timelines: the same action shifted −2…+2 settlement periods")

        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            chosen = st.selectbox(
                "Decision", options=list(labels), format_func=labels.get, key="audit_decision"
            )
        with c2:
            mode = st.radio(
                "Mode",
                [MODE_FORK, MODE_INPROCESS],
                horizontal=True,
                key="audit_mode",
                help="Fork mode takes a Tiger zero-copy fork of live data and replays on the Vultr pool. "
                "In-process is the on-stage fallback: same replay, run locally.",
            )
        with c3:
            st.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
            run = st.button("Run timing audit", type="primary", key="audit_run", disabled=running)

        if run and not running:
            st.session_state["audit_action"] = decisions.set_index("decision_id").action.get(chosen, "hold")
            for key in ("audit_result", "audit_log", "audit_error", "audit_elapsed"):
                st.session_state.pop(key, None)
            if mode == MODE_FORK:
                job = src.start_fork_audit(chosen)
                if job.done:
                    _store_result(job, src)
                else:
                    st.session_state["audit_job"] = job
                    running = True
            else:
                with st.spinner("Replaying five timelines…"):
                    st.session_state["audit_result"] = src.run_audit(chosen)
                st.session_state["audit_mode_used"] = "in-process"
            if not running:
                st.rerun()

        show_notes(src, "recent_decisions", "fork_audit")
        if running:
            st.info(
                "Audit running: one Tiger fork of live data, five Vultr workers. "
                "The button unlocks when done."
            )
            audit_progress_view()
        elif rows is not None:
            render_audit_result(src, rows)
        else:
            st.info(
                "Pick a decision and press Run. Five timelines, shifts −2..+2, the real decision in the "
                "middle."
            )

        sg = src.self_grade()
        st.markdown(
            f"Self-grade: timing within one settlement period of hindsight-optimal on "
            f"**{sg['pct_within_one_period']:.0f}%** of {sg['n_cycles']} cycles; mean cost of mistiming "
            f"£{sg['mean_cost_of_mistiming_gbp']:.2f} per cycle."
        )
        show_notes(src, "self_grade")


# ---------------------------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------------------------


def section_honesty(src) -> None:
    summary = src.backtest_summary()
    main = main_strategy_row(summary)
    weeks = src.backtest_weeks()
    if main is not None:
        name = main.strategy.split(" (")[0]
        sentence = f"{name} captures {main.pct_of_perfect:.1f}% of perfect-foresight profit" + (
            f" over {weeks} unseen weeks." if weeks else "."
        )
    else:
        sentence = "No backtest results yet."
    with ui.panel("honesty"):
        ui.section("Honesty", sentence, "honesty", aside="walk-forward backtest, honest baselines")

        ui.fig_label("4.1", "Walk-forward backtest on unseen weeks, % of perfect foresight")
        st.altair_chart(
            ui.ladder(summary, main_prefix=main.strategy if main is not None else "tempo"), width="stretch"
        )
        with st.expander("Backtest table"):
            st.dataframe(
                summary.style.format({"pnl_gbp": "£{:,.0f}", "pct_of_perfect": "{:.1f}%"}),
                hide_index=True,
                width="stretch",
            )

        c1, c2 = st.columns(2)
        with c1:
            ui.fig_label("4.2", "Calibration: share of actual prices under each forecast quantile")
            cal = src.calibration()
            line = (
                alt.Chart(cal)
                .mark_line(point=True, color=T.BELIEF)
                .encode(x=alt.X("nominal:Q", title="nominal"), y=alt.Y("observed:Q", title="observed"))
            )
            diag = (
                alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]}))
                .mark_line(strokeDash=[4, 4], color=T.PERFECT)
                .encode(x="x:Q", y="y:Q")
            )
            st.altair_chart((line + diag).properties(height=240), width="stretch")
            if cal.attrs.get("n"):
                st.caption(calibration_sentence(cal.attrs["n"], cal.attrs.get("coverage_p10_p90")))
        with c2:
            ui.fig_label("4.3", "By regime: calm weeks vs windy weeks")
            reg = src.backtest_by_regime()
            st.altair_chart(
                alt.Chart(reg)
                .mark_bar(cornerRadiusEnd=3)
                .encode(
                    x=alt.X("strategy:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=90)),
                    y=alt.Y("pct_of_perfect:Q", title="% of perfect"),
                    color=alt.Color(
                        "regime:N", scale=alt.Scale(range=[T.HOLD, T.BELIEF]), legend=alt.Legend(title=None)
                    ),
                    xOffset="regime:N",
                    tooltip=["regime:N", "strategy:N", "pct_of_perfect:Q", "pnl_gbp:Q"],
                )
                .properties(height=240),
                width="stretch",
            )

        ui.eyebrow("Where it's weak")
        weak = src.weak_points()
        cols = st.columns(min(3, max(1, len(weak))))
        for i, line_ in enumerate(weak):
            with cols[i % len(cols)], st.container(border=True):
                st.markdown(line_)
        stats = src.storage_stats()
        before, after = stats.get("before_bytes") or 0, stats.get("after_bytes") or 0
        saved = 100 * (1 - after / before) if before else 0.0
        st.caption(
            f"Storage · {stats['rows']:,} rows in grid_raw · compressed {saved:.0f}% "
            f"({stats['ratio']:.1f}×) · price assumption: APX MID is the tradeable price, available "
            "period end + 10 min."
        )
        show_notes(
            src, "backtest_summary", "backtest_by_regime", "calibration", "weak_points", "storage_stats"
        )


# ---------------------------------------------------------------------------------------------
# About: two text panels, like the site's closing pair
# ---------------------------------------------------------------------------------------------


def section_about() -> None:
    b = settings().battery
    left, right = st.columns(2)
    with left, ui.panel("about"):
        ui.section(
            "How Tempo works",
            "Most projects stop at a prediction. Tempo turns it into a decision, then proves the timing.",
            "about",
        )
        st.markdown(
            f"""
<div class="tempo-prose">
<p>Great Britain's wholesale electricity market splits every day into 48 half-hour settlement periods, each
with its own price. On a windy night prices fall, sometimes below zero; on a cold weekday evening they
spike. A grid battery earns the difference by charging when power is cheap and selling it back when it is
dear, minus what it loses on the way round.</p>
<p>Tempo forecasts the next 24 hours of prices as a range (p10, p50, p90) with a LightGBM quantile model
trained on Elexon data in Tiger Data, then a cost-gated optimiser turns the median into a 48-period plan.
Doing nothing is a real decision: when the expected spread does not cover the round-trip loss and the
wear on the cells, Tempo holds and says why.</p>
<p>Every decision can then be audited. One click takes a zero-copy fork of the live database and replays
the same action in five parallel timelines, shifted up to an hour either way, on five Vultr workers.
The result is one sentence: what the chosen moment was worth against its neighbours.</p>
<table>
<tr><th>Battery</th><th>Value</th></tr>
<tr><td>Capacity</td><td>{b.capacity_mwh:g} MWh</td></tr>
<tr><td>Power</td><td>{b.power_mw:g} MW</td></tr>
<tr><td>Round-trip efficiency</td><td>{100 * b.rt_efficiency:.0f}%</td></tr>
<tr><td>Cycle cost</td><td>£{b.cycle_cost_gbp:g}/MWh</td></tr>
<tr><td>Price series</td><td>APX MID, available period end + 10 min</td></tr>
</table>
</div>
""",
            unsafe_allow_html=True,
        )
    with right, ui.panel("about-site"):
        ui.panel_head("About this project")
        st.markdown(
            f"""
<div class="tempo-prose">
<p>Tempo was built by Ayo, Ernqi and Girik at OxHack 2026 (theme: TIME) for the HRT track, Best Use of
Data for Predictions and Decision Making. The <a href="{REPO_URL}">code is on GitHub</a>.</p>
<p><b>Data:</b> Elexon BMRS, availability-time stamped, in Tiger Data hypertables with hierarchical
continuous aggregates. <b>Brain:</b> p10/p50/p90 LightGBM forecast, cost-gated optimiser, walk-forward
backtest against honest baselines. <b>Stage:</b> each click takes a Tiger zero-copy fork of live data;
five pre-warmed Vultr workers replay five timelines inside it in parallel.</p>
<p>Assumptions on screen: APX MID is the tradeable price; MID availability is period end + 10 minutes;
a real unit would trade day-ahead. The p10–p90 band is reported against its 80% target, and the backtest
ladder always shows the simple rule and persistence baselines next to Tempo.</p>
<p>The data comes from the <a href="https://bmrs.elexon.co.uk/">Elexon Insights Solution</a>, stored in
<a href="https://www.tigerdata.com/">Tiger Data</a> and served from <a href="https://www.vultr.com/">Vultr</a>.
Elexon's licence requires the following statement: Contains BMRS data © Elexon Limited copyright and
database right 2026. The page layout follows <a href="https://grid.iamkate.com/">National Grid: Live</a>
by Kate Morley, published under CC0.</p>
</div>
""",
            unsafe_allow_html=True,
        )


def main() -> None:
    ui.inject_css()
    src, _ = get_source()
    top = st.container()  # filled last, so the status pills reflect the notes the sections set
    section_live(src)
    section_replay(src)
    section_audit(src)
    section_honesty(src)
    section_about()
    with top:
        header_strip()


main()
