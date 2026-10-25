"""Streamlit app: the Tempo dashboard as one "Report" page.

Owner: Ayo. See docs/ayo.md. Run with `make dashboard` or `streamlit run tempo/dashboard/app.py`.

Sections in demo order, each opened by a gradient eyebrow and a sentence built from real numbers: Live,
Replay, Timing audit, Honesty, About. The Live section is laid out like a live grid monitor: stat cards on
top, then coloured banner panels either side of a donut of today's 48-period schedule. With
TEMPO_DATABASE_URL set every section reads `DbSource`; a query that hits a missing or empty table falls
back to synthetic data and says so in a note under that section. The Timing audit button takes a Tiger fork
and replays on the Vultr pool in a background job (fork mode), or replays in-process (the on-stage
fallback).
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

st.set_page_config(page_title="Tempo", page_icon="⚡", layout="wide")

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
GRAD_GOOD = f"linear-gradient(100deg, {T.GOOD} 0%, #4cc38a 100%)"


@st.cache_resource
def get_source():
    return pick_source(settings().database_url)


@st.cache_data(ttl=60, show_spinner=False)
def worker_health() -> tuple[int, int, str] | None:
    """(healthy, total, kind) for the status dot; None when no pool can be found. Cached 60 s."""
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


def hhmm(ts) -> str:
    return f"{T.local_naive(ts):%H:%M}"


# ---------------------------------------------------------------------------------------------
# Header strip
# ---------------------------------------------------------------------------------------------


@st.fragment(run_every="30s")
def header_strip() -> None:
    src, note = get_source()
    midnight, period = current_settlement_period()
    now_local = T.local_naive(datetime.now(tz=UTC))
    with st.container(key="hero"):
        st.html(
            '<div class="tp-byline">A project for <b>OxHack 2026</b> · theme TIME'
            '<span class="tp-chip">HRT track</span></div>'
        )
        st.title("Tempo")
        st.html(
            '<div class="tp-tagline"><span class="tp-live"></span><b>Live</b> · when a grid battery should '
            "charge, sell or hold on the GB half-hourly market, and proof it picked the right moment</div>"
        )
        st.caption(
            f"{midnight:%A %d %B %Y} · settlement period {period} · {now_local:%H:%M} UK · "
            + " · ".join(f"[{label}](#{anchor})" for anchor, label in SECTIONS)
        )
        summary = src.backtest_summary()
        main = main_strategy_row(summary)
        if main is not None:
            weeks = src.backtest_weeks()
            name = main.strategy.split(" (")[0]
            st.markdown(
                f"**[{name} captures {main.pct_of_perfect:.1f}% of perfect foresight"
                + (f" over {weeks} unseen weeks" if weeks else "")
                + "](#honesty)**"
            )
        health = worker_health()
        synthetic = bool(src.notes) or src.name == "synthetic"
        dots: list[tuple[bool | None, str]] = [(src.name != "synthetic", f"Tiger: {note}")]
        if health is None:
            dots.append((False, "workers: none"))
        else:
            ok, total, kind = health
            kind_label = "Vultr " if kind == "http" else "local "
            dots.append((ok == total and total > 0, f"{ok}/{total} {kind_label}workers"))
        dots.append((None if synthetic else True, "synthetic data in use" if synthetic else "all data live"))
        ui.status_strip(dots)


# ---------------------------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------------------------


def action_blocks(sched: pd.DataFrame, fc: pd.DataFrame) -> list[dict]:
    """Left banner panel: one banner per action with its share of the 48 periods, energy and prices."""
    try:
        merged = sched.merge(fc[["target_time", "p50"]], on="target_time", how="left")
    except (KeyError, ValueError, TypeError):
        merged = sched.assign(p50=float("nan"))
    n = max(len(merged), 1)
    blocks = []
    spec = [
        ("charge", T.GRAD_CHARGE, "Charge", "energy bought", "first charge"),
        ("discharge", T.GRAD_SELL, "Sell", "energy sold", "first sale"),
    ]
    for action, grad, name, energy, first_label in spec:
        part = merged[merged.action == action]
        colour = T.ACTION_COLOUR[action]
        avg = part.p50.mean() if len(part) else None
        blocks.append(
            {
                "grad": grad,
                "value": (f"{len(part)}", " periods"),
                "share": (f"{100 * len(part) / n:.1f}", "%"),
                "name": name,
                "rows": [
                    {"colour": colour, "value": (f"{part.mw.abs().sum() * 0.5:.1f}", "MWh"), "name": energy},
                    {
                        "colour": colour + "99",
                        "value": (ui.gbp(avg) if avg is not None and not pd.isna(avg) else "—", "/MWh"),
                        "name": "avg forecast price",
                    },
                    {
                        "colour": colour + "55",
                        "value": (hhmm(part.target_time.iloc[0]) if len(part) else "—", ""),
                        "name": first_label,
                    },
                ],
            }
        )
    holds = merged[merged.action == "hold"]
    spread = holds.expected_spread.mean() if len(holds) else None
    blocks.append(
        {
            "grad": T.GRAD_HOLD,
            "value": (f"{len(holds)}", " periods"),
            "share": (f"{100 * len(holds) / n:.1f}", "%"),
            "name": "Hold",
            "rows": [
                {
                    "colour": T.HOLD,
                    "value": (ui.gbp(spread) if spread is not None and not pd.isna(spread) else "—", "/MWh"),
                    "name": "avg expected spread",
                },
                {
                    "colour": T.HOLD + "77",
                    "value": (hhmm(holds.target_time.iloc[0]) if len(holds) else "—", ""),
                    "name": "first hold",
                },
            ],
        }
    )
    return blocks


def market_blocks(prices: pd.DataFrame, fc: pd.DataFrame) -> list[dict]:
    """Right banner panel: the forecast for the next 24 h and the market over the last 24 h."""
    blocks = []
    if not fc.empty:
        lo, hi = fc.loc[fc.p50.idxmin()], fc.loc[fc.p50.idxmax()]
        blocks.append(
            {
                "grad": T.GRAD_FORECAST,
                "value": (ui.gbp(fc.p50.mean()), "/MWh"),
                "name": "Forecast, next 24 h",
                "rows": [
                    {
                        "colour": T.CHARGE,
                        "value": (ui.gbp(lo.p50), "/MWh"),
                        "name": f"cheapest at {hhmm(lo.target_time)}",
                    },
                    {
                        "colour": T.DISCHARGE,
                        "value": (ui.gbp(hi.p50), "/MWh"),
                        "name": f"dearest at {hhmm(hi.target_time)}",
                    },
                    {
                        "colour": T.BELIEF,
                        "value": (ui.gbp((fc.p90 - fc.p10).mean()), "/MWh"),
                        "name": "p10–p90 band, avg",
                    },
                ],
            }
        )
    if not prices.empty:
        blocks.append(
            {
                "grad": T.GRAD_NAVY,
                "value": (ui.gbp(prices.price.iloc[-1]), "/MWh"),
                "name": "APX price, last 24 h",
                "rows": [
                    {"colour": T.SKY, "value": (ui.gbp(prices.price.min()), "/MWh"), "name": "24 h low"},
                    {"colour": T.MLH_RED, "value": (ui.gbp(prices.price.max()), "/MWh"), "name": "24 h high"},
                    {"colour": T.PERFECT, "value": (f"{len(prices)}", " periods"), "name": "priced"},
                ],
            }
        )
    return blocks


def section_live(src) -> None:
    now = datetime.now(tz=UTC)
    midnight, period = current_settlement_period(now)
    prices = src.recent_prices(24)
    fc = src.next_forecast()
    sched = src.todays_schedule()
    hold = src.latest_hold()

    upcoming = sched[(sched.action != "hold")] if not sched.empty else sched
    if not sched.empty and not upcoming.empty:
        nxt = upcoming.iloc[0]
        glyph = T.ACTION_GLYPH.get(nxt.action, "")
        label = T.ACTION_LABEL.get(nxt.action, nxt.action)
        next_short = f"{glyph} {label} {abs(nxt.mw):.0f} MW"
        next_text = f"{next_short} at {T.local_naive(nxt.target_time):%H:%M}"
    else:
        next_short, next_text = "—", "no live schedule yet"
    ui.section("live", f"{midnight:%A %d %B}, period {period} of 48: {next_text}.", "live", T.GRAD_SELL)

    left, right = st.columns([1.15, 1], gap="medium")
    with left, st.container(key="card-stats-now"):
        c1, c2, c3 = st.columns(3)
        with c1:
            ui.pill("Current period", f"{period} / 48", f"{T.local_naive(now):%H:%M} UK time")
        with c2:
            latest = prices.iloc[-1] if not prices.empty else None
            ui.pill("Latest APX price", f"£{latest.price:,.2f}" if latest is not None else "—", "£/MWh")
        with c3:
            ui.pill("Next action", next_short)
    with right, st.container(key="card-stats-spread"):
        c1, op1, c2, op2, c3 = st.columns([1.2, 0.2, 1, 0.2, 1])
        with c1:
            spread = (fc.p50.max() - fc.p50.min()) if not fc.empty else None
            ui.pill("Forecast spread, next 24 h", f"£{spread:,.0f}" if spread is not None else "—", "£/MWh")
        with op1:
            ui.operator("=")
        with c2:
            ui.pill("Highest p50", f"£{fc.p50.max():,.0f}" if not fc.empty else "—", "£/MWh")
        with op2:
            ui.operator("−")
        with c3:
            ui.pill("Lowest p50", f"£{fc.p50.min():,.0f}" if not fc.empty else "—", "£/MWh")

    st.html('<div style="height:0.6rem"></div>')
    if not sched.empty:
        lp, m, r = st.columns([1.1, 1, 1.1], vertical_alignment="center", gap="small")
        with lp:
            ui.banner_panel(action_blocks(sched, fc), "left")
        with m, st.container(key="donut"):
            st.altair_chart(ui.schedule_donut(sched), width="content")
        with r:
            ui.banner_panel(market_blocks(prices, fc), "right")
    else:
        st.info("No live decisions yet: the decision engine writes the first 48-period schedule in Phase 2.")

    st.html('<div style="height:0.8rem"></div>')
    with st.container(key="card-price"):
        ui.fig_label("1.1", "APX MID price per MWh: last 24 h actual, next 24 h forecast with p10–p90 band")
        st.altair_chart(ui.price_chart(prices, fc, now, sched), width="stretch")
    if not sched.empty:
        with st.container(key="card-strip"):
            ui.fig_label(
                "1.2", "Today's schedule, 48 periods (charge ▲, sell ▼, hold —), current period outlined"
            )
            st.altair_chart(ui.period_strip(sched, now), width="stretch", height=T.STRIP_H + 96)
    if hold:
        ui.hold_card(hold)
    show_notes(src, "recent_prices", "next_forecast", "todays_schedule", "latest_hold")


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
    # first.day, not %-d: %-d is glibc-only and raises on Windows.
    span = (
        f"{first.day} to {last.day} {last:%B %Y}"
        if first.month == last.month
        else f"{first.day} {first:%B} to {last.day} {last:%B %Y}"
    )
    ui.section(
        "replay", f"The windy week of {span}, played forward: {ui.gbp(pnl)} so far.", "replay", T.GRAD_CHARGE
    )
    with st.container(key="card-replay-slider"):
        st.slider("Periods played", min_value=1, max_value=n, value=min(96, n), step=1, key="replay_upto")
    playhead = week.ts.iloc[upto - 1]
    st.html('<div style="height:0.6rem"></div>')
    with st.container(key="card-replay-price"):
        ui.fig_label("2.1", "Forecast band vs actual price per MWh, with the playhead")
        actual = shown.rename(columns={"ts": "bucket", "actual": "price"})[["bucket", "price"]]
        fc = shown.rename(columns={"ts": "target_time"})[["target_time", "p10", "p50", "p90"]]
        st.altair_chart(ui.price_chart(actual, fc, playhead), width="stretch")
    soc = T.localise(shown[["ts", "soc_mwh"]], ["ts"])
    cum = T.localise(shown[["ts", "cum_pnl_gbp"]], ["ts"])
    st.html('<div style="height:0.6rem"></div>')
    c1, c2 = st.columns(2, gap="medium")
    with c1, st.container(key="card-replay-soc"):
        ui.fig_label("2.2", "State of charge, MWh")
        st.altair_chart(
            alt.Chart(soc)
            .mark_area(
                color=T.vega_gradient("rgba(29,83,159,0.55)", "rgba(61,139,253,0.05)"),
                line={"color": T.CHARGE, "strokeWidth": 2},
                interpolate="step-after",
            )
            .encode(x=T.time_axis("ts"), y=alt.Y("soc_mwh:Q", title="MWh", scale=alt.Scale(domain=[0, 2])))
            .properties(height=T.SECONDARY_H),
            width="stretch",
        )
    with c2, st.container(key="card-replay-pnl"):
        ui.fig_label("2.3", "Cumulative profit, £")
        st.altair_chart(
            alt.Chart(cum)
            .mark_area(
                color=T.vega_gradient("rgba(31,157,85,0.45)", "rgba(31,157,85,0.03)"),
                line={"color": T.GOOD, "strokeWidth": 2.2},
                interpolate="step-after",
            )
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


def shift_title(shift: int) -> str:
    return f"★ {SHIFT_LABELS[shift]}" if shift == 0 else SHIFT_LABELS[shift]


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
        with col, st.container(key=f"card-shift-run-{shift + 2}"):
            ui.shift_banner(shift_title(shift), T.GRAD_NAVY if shift == 0 else T.GRAD_GREY)
            st.markdown(f"{STATE_ICON.get(state, '○')} {jobs.STATE_LABEL.get(state, state)}")
            st.caption(job.progress.workers.get(shift) or "")
    st.caption(f"elapsed {job.running_s:04.1f} s")
    st.code("\n".join(job.log_lines()) or "starting…", language="text")


def render_audit_result(src, rows: pd.DataFrame) -> None:
    cols = st.columns(len(SHIFTS))
    for col, shift in zip(cols, SHIFTS, strict=True):
        r = rows[rows["shift"] == shift].iloc[0]
        if shift == 0:
            grad = T.GRAD_NAVY
        elif pd.isna(r.pnl_delta_gbp):
            grad = T.GRAD_GREY
        else:
            grad = GRAD_GOOD if r.pnl_delta_gbp > 0 else T.GRAD_SELL
        with col, st.container(key=f"card-shift-{shift + 2}"):
            ui.shift_banner(shift_title(shift), grad)
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
    st.html('<div style="height:0.6rem"></div>')
    c1, c2 = st.columns([3, 2], gap="medium")
    with c1, st.container(key="card-audit-delta"):
        ui.fig_label("3.2", "Cost of mistiming, £ versus as decided")
        st.altair_chart(ui.delta_bars(rows), width="stretch")
    with c2, st.container(key="card-audit-log"):
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
    ui.section(
        "timing audit",
        sentence or "Click a decision: one Tiger fork, five timelines, five Vultr workers.",
        "audit",
        T.GRAD_NAVY,
    )

    with st.container(key="card-audit-controls"):
        ui.fig_label("3.1", "Five timelines: the same action shifted −2…+2 settlement periods")
        c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="bottom")
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
            run = st.button(
                "Run timing audit", type="primary", key="audit_run", disabled=running, width="stretch"
            )

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

    st.html('<div style="height:0.6rem"></div>')
    show_notes(src, "recent_decisions", "fork_audit")
    if running:
        st.info(
            "Audit running: one Tiger fork of live data, five Vultr workers. The button unlocks when done."
        )
        audit_progress_view()
    elif rows is not None:
        render_audit_result(src, rows)
    else:
        st.info(
            "Pick a decision and press Run. Five timelines, shifts −2..+2, the real decision in the middle."
        )

    sg = src.self_grade()
    st.html('<div style="height:0.6rem"></div>')
    with st.container(key="card-selfgrade"):
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
    ui.section("honesty", sentence, "honesty", T.GRAD_FORECAST)

    g, lad = st.columns([1, 2.6], gap="medium")
    with g, st.container(key="card-gauge"):
        ui.fig_label("4.0", "Share of the best possible profit")
        if main is not None:
            with st.container(key="donut-gauge"):
                st.altair_chart(ui.gauge(float(main.pct_of_perfect), "of perfect foresight"), width="content")
            st.caption(
                f"{main.strategy.split(' (')[0]}, walk-forward" + (f", {weeks} unseen weeks" if weeks else "")
            )
    with lad, st.container(key="card-ladder"):
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

    c1, c2 = st.columns(2, gap="medium")
    with c1, st.container(key="card-calibration"):
        ui.fig_label("4.2", "Calibration: share of actual prices under each forecast quantile")
        cal = src.calibration()
        line = (
            alt.Chart(cal)
            .mark_line(point={"filled": True, "size": 70, "color": T.BELIEF}, color=T.BELIEF, strokeWidth=2.5)
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
    with c2, st.container(key="card-regime"):
        ui.fig_label("4.3", "By regime: calm weeks vs windy weeks")
        reg = src.backtest_by_regime()
        st.altair_chart(
            alt.Chart(reg)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("strategy:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=90)),
                y=alt.Y("pct_of_perfect:Q", title="% of perfect"),
                color=alt.Color(
                    "regime:N", scale=alt.Scale(range=[T.HOLD, T.MLH_BLUE]), legend=alt.Legend(title=None)
                ),
                xOffset="regime:N",
                tooltip=["regime:N", "strategy:N", "pct_of_perfect:Q", "pnl_gbp:Q"],
            )
            .properties(height=240),
            width="stretch",
        )

    ui.eyebrow("where it's weak", T.GRAD_GREY)
    weak = src.weak_points()
    cols = st.columns(min(3, max(1, len(weak))), gap="medium")
    for i, line_ in enumerate(weak):
        with cols[i % len(cols)], st.container(key=f"card-weak-{i}"):
            st.markdown(line_)
    stats = src.storage_stats()
    before, after = stats.get("before_bytes") or 0, stats.get("after_bytes") or 0
    saved = 100 * (1 - after / before) if before else 0.0
    st.caption(
        f"Storage · {stats['rows']:,} rows in grid_raw · compressed {saved:.0f}% ({stats['ratio']:.1f}×) · "
        "price assumption: APX MID is the tradeable price, available period end + 10 min."
    )
    show_notes(src, "backtest_summary", "backtest_by_regime", "calibration", "weak_points", "storage_stats")


# ---------------------------------------------------------------------------------------------
# About
# ---------------------------------------------------------------------------------------------


PIPELINE = [
    (T.GRAD_GREY, "Elexon BMRS", "prices, wind, demand, every half hour"),
    (T.GRAD_NAVY, "Tiger Data", "hypertables, aggregates, zero-copy forks"),
    (T.GRAD_FORECAST, "LightGBM forecast", "p10 / p50 / p90, 48 periods ahead"),
    (T.GRAD_CHARGE, "Cost-gated optimiser", "charge, sell or hold"),
    (T.GRAD_SELL, "Vultr workers", "five timelines replayed in parallel"),
]


def pipeline_html() -> str:
    steps = "".join(
        f'<div style="background:{g}">{name}<span>{what}</span></div>' for g, name, what in PIPELINE
    )
    return f'<div class="tp-stack">{steps}</div>'


def section_about() -> None:
    ui.section(
        "about",
        "Most projects stop at a prediction. Tempo turns it into a decision, then proves the timing.",
        "about",
        T.GRAD_GREY,
    )
    c1, c2 = st.columns([1.5, 1], gap="medium")
    with c1:
        ui.info_box(
            "How Tempo works",
            "<p><b>Tempo</b> decides when a 2 MWh / 1 MW grid battery should charge, sell or hold on the GB "
            "half-hourly market, then proves whether each decision was made at the right moment by replaying "
            "it in five parallel timelines shifted −2..+2 settlement periods.</p><ul>"
            "<li><b>Data:</b> Elexon BMRS, availability-time stamped, in Tiger Data hypertables with "
            "hierarchical continuous aggregates.</li>"
            "<li><b>Brain:</b> p10/p50/p90 LightGBM forecast, cost-gated optimiser, walk-forward backtest "
            "against honest baselines.</li>"
            "<li><b>Stage:</b> each click takes a Tiger zero-copy fork of live data; five pre-warmed Vultr "
            "workers replay five timelines inside it in parallel.</li></ul>"
            "<p>OxHack 2026, theme TIME, HRT track. Assumptions on screen: APX MID is the tradeable price; "
            "MID "
            "availability is period end + 10 min.</p>",
            T.GRAD_GREY,
        )
    with c2:
        ui.info_box(
            "The pipeline",
            pipeline_html(),
            T.GRAD_NAVY,
        )
    st.html(
        '<div class="tp-footer">Tempo · OxHack 2026 · data from Elexon BMRS · '
        "all times UK local · numbers on this page are read live from the database</div>"
    )


def main() -> None:
    ui.inject_css()
    src, _ = get_source()
    top = st.container()  # filled last, so the status dots reflect the notes the sections set
    section_live(src)
    st.divider()
    section_replay(src)
    st.divider()
    section_audit(src)
    st.divider()
    section_honesty(src)
    st.divider()
    section_about()
    with top:
        header_strip()
        st.divider()


main()
