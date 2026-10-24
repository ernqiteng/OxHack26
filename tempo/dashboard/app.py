"""Streamlit app: Live, Replay, Timing audit, Honesty, About.

Owner: Ayo. See docs/ayo.md. Run with `make dashboard` or `streamlit run tempo/dashboard/app.py`.

With TEMPO_DATABASE_URL set, every tab reads from `DbSource`; each query that hits a missing or empty table
falls back to synthetic data and the tab shows a yellow note saying so. The Timing audit button runs
`run_audit(mode='inprocess')` against real decisions. Phase 2 adds fork mode and live progress.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from tempo.config import settings
from tempo.dashboard import jobs
from tempo.dashboard.data import (
    SHIFTS,
    current_settlement_period,
    pick_source,
)

st.set_page_config(page_title="Tempo", page_icon="⚡", layout="wide")

CACHE_TTL = 30


@st.cache_resource
def get_source():
    return pick_source(settings().database_url)


def show_notes(src, *methods: str) -> None:
    for m in methods:
        note = src.notes.get(m)
        if note:
            st.warning(f"{m}: {note}", icon="⚠️")


def gbp(x: float | None) -> str:
    return "failed" if x is None or pd.isna(x) else f"£{x:,.2f}"


def price_chart(df: pd.DataFrame, x: str, y: str, band: tuple[str, str] | None = None, title: str = ""):
    base = alt.Chart(df).encode(x=alt.X(f"{x}:T", title="time (UTC)"))
    layers = []
    if band:
        layers.append(
            base.mark_area(opacity=0.25).encode(y=alt.Y(f"{band[0]}:Q", title="£/MWh"), y2=f"{band[1]}:Q")
        )
    layers.append(base.mark_line().encode(y=alt.Y(f"{y}:Q", title="£/MWh")))
    return alt.layer(*layers).properties(height=260, title=title)


# ---------------------------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------------------------


def tab_live(src) -> None:
    midnight, period = current_settlement_period()
    c1, c2, c3 = st.columns(3)
    c1.metric("Settlement date", midnight.strftime("%a %d %b %Y"))
    c2.metric("Current settlement period", f"{period} / 48")
    hold = src.latest_hold()
    c3.metric("Latest hold", "yes" if hold else "none", help=hold.reason if hold else None)

    prices = src.recent_prices(24)
    st.altair_chart(price_chart(prices, "bucket", "price", title="APX MID, last 24 h"), width="stretch")

    fc = src.next_forecast()
    st.altair_chart(
        price_chart(fc, "target_time", "p50", band=("p10", "p90"), title="Next 24 h forecast, p10-p90 band"),
        width="stretch",
    )

    st.subheader("Today's schedule (run_id = live)")
    sched = src.todays_schedule()
    if sched.empty:
        st.info("No live decisions yet. The engine writes them in Phase 2.")
    else:
        colour = alt.Scale(domain=["charge", "discharge", "hold"], range=["#2a9d8f", "#e76f51", "#bbbbbb"])
        chart = (
            alt.Chart(sched)
            .mark_bar()
            .encode(
                x=alt.X("target_time:T", title="target period (UTC)"),
                y=alt.Y("mw:Q", title="MW (+ charge, − discharge)"),
                color=alt.Color("action:N", scale=colour),
                tooltip=["target_time:T", "action", "mw", "reason"],
            )
            .properties(height=180)
        )
        st.altair_chart(chart, width="stretch")
    if hold:
        st.warning(f"Most recent hold for {hold.target_time:%H:%M} UTC: {hold.reason}")
    show_notes(src, "recent_prices", "next_forecast", "todays_schedule", "latest_hold")


def tab_replay(src) -> None:
    week = src.replay_week()
    n = len(week)
    st.caption("A windy week replayed period by period: forecast band vs actual, battery SoC, cumulative £.")
    upto = st.slider("Periods played", min_value=1, max_value=n, value=min(96, n), step=1, key="replay_upto")
    shown = week.iloc[:upto]
    st.altair_chart(
        price_chart(shown, "ts", "actual", band=("p10", "p90"), title="Forecast band vs actual"),
        width="stretch",
    )
    c1, c2 = st.columns(2)
    c1.altair_chart(
        alt.Chart(shown)
        .mark_line()
        .encode(x="ts:T", y=alt.Y("soc_mwh:Q", title="SoC (MWh)"))
        .properties(height=200, title="Battery state of charge"),
        width="stretch",
    )
    c2.altair_chart(
        alt.Chart(shown)
        .mark_line()
        .encode(x="ts:T", y=alt.Y("cum_pnl_gbp:Q", title="£"))
        .properties(height=200, title="Cumulative PnL"),
        width="stretch",
    )
    st.metric("PnL so far", gbp(float(shown.cum_pnl_gbp.iloc[-1])))
    show_notes(src, "replay_week")


SHIFT_LABELS = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}
STATE_ICON = {"queued": "○", "forking": "◌", "ready": "◍", "replaying": "◉", "done": "✓", "failed": "✗"}
MODE_INPROCESS, MODE_FORK = "in-process", "Tiger fork + Vultr workers"


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
        with col:
            st.markdown(f"**{SHIFT_LABELS[shift]}**" if shift else f"**:blue[{SHIFT_LABELS[shift]}]**")
            st.markdown(f"{STATE_ICON.get(state, '○')} {jobs.STATE_LABEL.get(state, state)}")
            worker = job.progress.workers.get(shift)
            st.caption(worker or "")
    st.caption(f"elapsed {job.running_s:04.1f} s")
    st.code("\n".join(job.log_lines()) or "starting…", language="text")


def render_audit_result(src, rows: pd.DataFrame) -> None:
    cols = st.columns(len(SHIFTS))
    for col, shift in zip(cols, SHIFTS, strict=True):
        r = rows[rows["shift"] == shift].iloc[0]
        with col:
            st.markdown(f"**{SHIFT_LABELS[shift]}**" if shift else f"**:blue[{SHIFT_LABELS[shift]}]**")
            st.metric(
                "PnL",
                gbp(r.pnl_gbp),
                delta=None if pd.isna(r.pnl_delta_gbp) or shift == 0 else f"{r.pnl_delta_gbp:+.2f}",
            )
            worker = r.worker_id if isinstance(r.worker_id, str) and r.worker_id else "in-process"
            st.caption(worker)
    errors = [(r.shift, r.error) for r in rows.itertuples() if isinstance(getattr(r, "error", None), str)]
    for shift, err in errors:
        st.error(f"shift {shift:+d} failed: {err}")
    if st.session_state.get("audit_error"):
        st.error(f"audit crashed: {st.session_state['audit_error']}")
    later = rows[rows["shift"] == 1].iloc[0]
    if not pd.isna(later.pnl_delta_gbp):
        verb = "cost" if later.pnl_delta_gbp < 0 else "earned"
        doing = {"charge": "Charging", "discharge": "Selling"}.get(
            st.session_state.get("audit_action"), "Acting"
        )
        st.success(f"{doing} one period later would have {verb} £{abs(later.pnl_delta_gbp):,.2f}.")
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
        with st.expander("Audit log", expanded=False):
            st.code("\n".join(log), language="text")
    st.dataframe(
        rows[["shift", "pnl_gbp", "pnl_delta_gbp", "mode", "worker_id", "fork_service_id"]],
        hide_index=True,
        width="stretch",
    )


def tab_audit(src) -> None:
    decisions = src.recent_decisions()
    labels = {
        int(r.decision_id): f"#{r.decision_id}  {r.decided_at:%d %b %H:%M}  {r.action}"
        + (f"  ({r.reason})" if r.reason else "")
        + ("  [rehearsal]" if getattr(r, "run_id", "live") == "selftest" else "")
        for r in decisions.itertuples()
    }
    job = st.session_state.get("audit_job")
    running = job is not None and not job.done
    chosen = st.selectbox("Decision", options=list(labels), format_func=labels.get, key="audit_decision")
    mode = st.radio(
        "Mode",
        [MODE_FORK, MODE_INPROCESS],
        horizontal=True,
        key="audit_mode",
        help="Fork mode takes a Tiger zero-copy fork of live data and replays on the Vultr pool. "
        "In-process is the on-stage fallback: same replay, run locally.",
    )
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

    show_notes(src, "recent_decisions", "fork_audit")
    if running:
        st.info(
            "Audit running: one Tiger fork of live data, five Vultr workers. The button unlocks when done."
        )
        audit_progress_view()
        return

    rows = st.session_state.get("audit_result")
    if rows is None:
        st.info(
            "Pick a decision and press Run. Five timelines, shifts −2..+2, the real decision in the middle."
        )
        return
    render_audit_result(src, rows)

    sg = src.self_grade()
    st.markdown(
        f"Self-grade: timing within one settlement period of hindsight-optimal on "
        f"**{sg['pct_within_one_period']:.0f}%** of {sg['n_cycles']} cycles; mean cost of mistiming "
        f"£{sg['mean_cost_of_mistiming_gbp']:.2f} per cycle."
    )
    show_notes(src, "self_grade")


def tab_honesty(src) -> None:
    st.subheader("Walk-forward backtest on unseen weeks")
    summary = src.backtest_summary()
    st.dataframe(
        summary.style.format({"pnl_gbp": "£{:,.0f}", "pct_of_perfect": "{:.1f}%"}),
        hide_index=True,
        width="stretch",
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Calibration** (share of actual prices under each quantile)")
        cal = src.calibration()
        line = (
            alt.Chart(cal)
            .mark_line(point=True)
            .encode(x=alt.X("nominal:Q", title="nominal"), y=alt.Y("observed:Q", title="observed"))
        )
        diag = (
            alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]}))
            .mark_line(strokeDash=[4, 4], color="grey")
            .encode(x="x:Q", y="y:Q")
        )
        st.altair_chart((line + diag).properties(height=240), width="stretch")
    with c2:
        st.markdown("**Regime breakdown**")
        reg = src.backtest_by_regime()
        st.altair_chart(
            alt.Chart(reg)
            .mark_bar()
            .encode(x="strategy:N", y=alt.Y("pct_of_perfect:Q", title="% of perfect"), column="regime:N")
            .properties(height=200),
            width="content",
        )
    st.markdown("**Where it's weak**")
    for line_ in src.weak_points():
        st.markdown(f"- {line_}")
    show_notes(src, "weak_points")
    stats = src.storage_stats()
    before, after = stats.get("before_bytes") or 0, stats.get("after_bytes") or 0
    saved = 100 * (1 - after / before) if before else 0.0
    st.caption(
        f"Storage: {stats['rows']:,} rows in grid_raw, compressed {saved:.0f}% ({stats['ratio']:.1f}×)."
    )
    show_notes(src, "backtest_summary", "backtest_by_regime", "calibration", "storage_stats")


def tab_about() -> None:
    st.markdown(
        """
**Tempo** decides when a 2 MWh / 1 MW grid battery should charge, sell or hold on the GB half-hourly market,
then proves whether each decision was made at the right moment by replaying it in five parallel timelines
shifted −2..+2 settlement periods.

- **Data:** Elexon BMRS, availability-time stamped, in Tiger Data hypertables with hierarchical
  continuous aggregates.
- **Brain:** p10/p50/p90 LightGBM forecast, cost-gated optimiser, walk-forward backtest against honest
  baselines.
- **Stage:** each click takes a Tiger zero-copy fork of live data; five pre-warmed Vultr workers replay
  five timelines inside it in parallel.

OxHack 2026, theme TIME, HRT track. Assumptions on screen: APX MID is the tradeable price; MID availability is
period end + 10 min.
"""
    )


def main() -> None:
    src, note = get_source()
    st.title("Tempo")
    st.caption(f"source: {src.name}. {note}")
    live, replay, audit, honesty, about = st.tabs(["Live", "Replay", "Timing audit", "Honesty", "About"])
    with live:
        tab_live(src)
    with replay:
        tab_replay(src)
    with audit:
        tab_audit(src)
    with honesty:
        tab_honesty(src)
    with about:
        tab_about()


main()
