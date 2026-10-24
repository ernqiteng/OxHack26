"""Streamlit app: Live, Replay, Timing audit, Honesty, About.

Owner: Ayo. See docs/ayo.md. Run with `make dashboard` or `streamlit run tempo/dashboard/app.py`.

Phase 0: every tab renders from `SyntheticSource`. Phase 1 swaps in `DbSource` for the live tabs and wires the
Timing audit button to `run_audit(mode='inprocess')`. Phase 2 adds the fork mode toggle and live progress.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from tempo.config import settings
from tempo.dashboard.data import (
    SHIFTS,
    SyntheticSource,
    current_settlement_period,
    pick_source,
)

st.set_page_config(page_title="Tempo", page_icon="⚡", layout="wide")

CACHE_TTL = 30


@st.cache_resource(ttl=CACHE_TTL)
def get_source():
    source, note = pick_source(settings().database_url)
    if not isinstance(source, SyntheticSource):
        # DbSource is incomplete until Phase 1; fall back so the app always renders.
        try:
            source.recent_prices()
        except NotImplementedError:
            source, note = SyntheticSource(), "DbSource not implemented yet: showing synthetic data"
    return source, note


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


def tab_audit(src) -> None:
    decisions = src.recent_decisions()
    labels = {
        int(r.decision_id): f"#{r.decision_id}  {r.decided_at:%d %b %H:%M}  {r.action}"
        + (f"  ({r.reason})" if r.reason else "")
        for r in decisions.itertuples()
    }
    chosen = st.selectbox("Decision", options=list(labels), format_func=labels.get, key="audit_decision")
    mode = st.radio(
        "Mode", ["in-process", "forks"], horizontal=True, key="audit_mode", help="Forks arrive in Phase 2"
    )
    run = st.button("Run timing audit", type="primary", key="audit_run")

    if run:
        st.session_state["audit_result"] = src.audit_rows(chosen)
        st.session_state["audit_mode_used"] = mode
    rows = st.session_state.get("audit_result")
    if rows is None:
        st.info(
            "Pick a decision and press Run. Five timelines, shifts −2..+2, the real decision in the middle."
        )
        return

    cols = st.columns(len(SHIFTS))
    for col, shift in zip(cols, SHIFTS, strict=True):
        r = rows[rows["shift"] == shift].iloc[0]
        label = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}[
            shift
        ]
        with col:
            st.markdown(f"**{label}**" if shift else f"**:blue[{label}]**")
            st.metric(
                "PnL",
                gbp(r.pnl_gbp),
                delta=None if pd.isna(r.pnl_delta_gbp) or shift == 0 else f"{r.pnl_delta_gbp:+.2f}",
            )
            st.caption(f"{r.worker_id or 'in-process'}")
    later = rows[rows["shift"] == 1].iloc[0]
    if not pd.isna(later.pnl_delta_gbp):
        verb = "cost" if later.pnl_delta_gbp < 0 else "earned"
        st.success(f"Charging one period later would have {verb} £{abs(later.pnl_delta_gbp):,.2f}.")
    elapsed = (rows.finished_at.max() - rows.started_at.min()).total_seconds()
    st.caption(f"mode: {st.session_state.get('audit_mode_used')}, total elapsed {elapsed:.0f} s")
    st.dataframe(
        rows[["shift", "pnl_gbp", "pnl_delta_gbp", "mode", "worker_id", "fork_service_id"]],
        hide_index=True,
        width="stretch",
    )

    sg = src.self_grade()
    st.markdown(
        f"Self-grade: timing within one settlement period of hindsight-optimal on "
        f"**{sg['pct_within_one_period']:.0f}%** of {sg['n_cycles']} cycles; mean cost of mistiming "
        f"£{sg['mean_cost_of_mistiming_gbp']:.2f} per cycle."
    )


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
    stats = src.storage_stats()
    st.caption(
        f"Storage: {stats['rows']:,} rows in grid_raw, "
        f"compressed {100 * (1 - stats['after_bytes'] / stats['before_bytes']):.0f}% "
        f"({stats['ratio']:.1f}×)."
    )


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
- **Stage:** each what-if runs in a Tiger zero-copy fork, replayed by a pre-warmed Vultr worker.

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
