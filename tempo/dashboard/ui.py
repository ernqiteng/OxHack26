"""Shared screen pieces for the dashboard (docs/ui.md section 6, docs/ui-plan.md section 4.4).

Owner: Ayo. Small helpers so every section is assembled from the same parts: eyebrow + serif heading,
stat pills, figure labels, the price chart with band / now-rule / action glyphs, the 48-period strip,
the backtest ladder, the delta bars, the hold card and the status dots in the header strip.
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from tempo.dashboard import theme as T


def gbp(x: float | None, dp: int = 2) -> str:
    return "failed" if x is None or pd.isna(x) else f"£{x:,.{dp}f}"


def eyebrow(text: str) -> None:
    """Mono, uppercase, letter-spaced section label. The one permitted CSS injection (ui-plan 5.1)."""
    st.html(
        "<div style=\"font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; "
        f"text-transform: uppercase; letter-spacing: 0.2em; color: {T.TEXT_SECONDARY}; "
        f'margin: 0 0 0.25rem 0;">{text}</div>'
    )


def section(label: str, sentence: str, anchor: str) -> None:
    """Eyebrow + serif h2 that is a real sentence with a real number (ui-plan 4.4)."""
    eyebrow(label)
    st.subheader(sentence, anchor=anchor)


def fig_label(n: str, title: str) -> None:
    st.caption(f"Fig {n} · {title}")


def status_dot(ok: bool | None, label: str) -> str:
    colour = T.GOOD if ok else (T.QUESTION if ok is None else T.BAD)
    return (
        '<span style="display:inline-flex;align-items:center;gap:0.4rem;margin-right:1.25rem;'
        f"font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:{T.INK}\">"
        f'<span style="width:0.55rem;height:0.55rem;border-radius:50%;background:{colour};'
        'display:inline-block"></span>'
        f"{label}</span>"
    )


def status_strip(items: list[tuple[bool | None, str]]) -> None:
    dots = "".join(status_dot(ok, lbl) for ok, lbl in items)
    st.html(f'<div style="margin:0.25rem 0 0.75rem 0">{dots}</div>')


def pill(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text, border=True)


# -- charts ------------------------------------------------------------------------------------


def price_chart(
    actual: pd.DataFrame | None,
    forecast: pd.DataFrame | None,
    now: datetime,
    actions: pd.DataFrame | None = None,
    height: int = T.DOMINANT_H,
) -> alt.LayerChart:
    """Fig 1.1: past actual (ink) and future p10-p90 band + p50 (belief), split by the now rule, with action
    glyphs along the bottom (ui.md 5.1). Any of the frames may be empty."""
    layers = []
    if forecast is not None and not forecast.empty:
        fc = T.localise(forecast.rename(columns={"target_time": "t"}), ["t"])
        base = alt.Chart(fc).encode(x=T.time_axis("t"))
        layers.append(
            base.mark_area(color=T.BELIEF, opacity=0.18).encode(
                y=alt.Y("p10:Q", title="£/MWh"), y2="p90:Q", tooltip=["t:T", "p10:Q", "p50:Q", "p90:Q"]
            )
        )
        layers.append(
            base.mark_line(color=T.BELIEF, strokeWidth=2).encode(y="p50:Q", tooltip=["t:T", "p50:Q"])
        )
    if actual is not None and not actual.empty:
        ac = T.localise(actual.rename(columns={"bucket": "t"}), ["t"])
        layers.append(
            alt.Chart(ac)
            .mark_line(color=T.INK, strokeWidth=2)
            .encode(x=T.time_axis("t"), y=alt.Y("price:Q", title="£/MWh"), tooltip=["t:T", "price:Q"])
        )
    if actions is not None and not actions.empty:
        acts = actions[actions.action != "hold"].rename(columns={"target_time": "t"})
        if not acts.empty:
            acts = T.localise(acts, ["t"]).assign(glyph=lambda d: d.action.map(T.ACTION_GLYPH))
            layers.append(
                alt.Chart(acts)
                .mark_text(size=12, baseline="bottom", dy=-2)
                .encode(
                    x=T.time_axis("t"),
                    y=alt.value(height - 14),
                    text="glyph:N",
                    color=alt.Color(
                        "action:N",
                        scale=alt.Scale(domain=list(T.ACTION_COLOUR), range=list(T.ACTION_COLOUR.values())),
                        legend=None,
                    ),
                    tooltip=["t:T", "action:N", "mw:Q", "reason:N"],
                )
            )
    layers.append(T.now_rule(now))
    return alt.layer(*layers).properties(height=height).resolve_scale(y="shared")


def period_strip(sched: pd.DataFrame, now: datetime) -> alt.LayerChart:
    """Fig 1.2: one cell per settlement period, coloured by action, current period outlined."""
    df = sched.rename(columns={"target_time": "t"}).copy()
    df["period"] = range(1, len(df) + 1)
    df["glyph"] = df.action.map(T.ACTION_GLYPH)
    df["label"] = df.action.map(T.ACTION_LABEL)
    df = T.localise(df, ["t"])
    current = T.local_naive(now)
    df["current"] = (df.t <= current) & (current < df.t + pd.Timedelta(minutes=30))
    base = alt.Chart(df).encode(
        x=alt.X("period:O", title=None, axis=alt.Axis(labelAngle=0, values=list(range(1, len(df) + 1, 4)))),
        tooltip=["period:O", "t:T", "label:N", "mw:Q", "expected_spread:Q", "reason:N"],
    )
    cells = base.mark_rect(cornerRadius=2).encode(
        color=alt.Color(
            "action:N",
            scale=alt.Scale(domain=list(T.ACTION_COLOUR), range=list(T.ACTION_COLOUR.values())),
            legend=alt.Legend(title=None, orient="top"),
        ),
        stroke=alt.condition("datum.current", alt.value(T.BRAND), alt.value(T.PAPER)),
        strokeWidth=alt.condition("datum.current", alt.value(2), alt.value(1)),
    )
    glyphs = base.mark_text(color=T.PAPER, size=9).encode(text="glyph:N")
    return (cells + glyphs).properties(height=T.STRIP_H)


def ladder(summary: pd.DataFrame, main_prefix: str = "tempo") -> alt.LayerChart:
    """Fig 4.1: horizontal bar ladder of % of perfect; the main strategy in brand green, others stone,
    perfect as a dashed rule at 100."""
    df = summary.copy()
    df["is_main"] = df.strategy.str.lower().str.startswith(main_prefix.lower())
    df["label"] = df.apply(lambda r: f"£{r.pnl_gbp:,.0f}  ·  {r.pct_of_perfect:.1f}%", axis=1)
    order = df.strategy.tolist()
    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y(
                "strategy:N", sort=order, title=None, axis=alt.Axis(labelLimit=320, labelFont="IBM Plex Sans")
            ),
            x=alt.X(
                "pct_of_perfect:Q",
                title="% of perfect foresight",
                scale=alt.Scale(domain=[0, 112]),
                axis=alt.Axis(values=[0, 25, 50, 75, 100]),
            ),
            color=alt.condition("datum.is_main", alt.value(T.BRAND), alt.value(T.HOLD)),
            tooltip=["strategy:N", "pnl_gbp:Q", "pct_of_perfect:Q"],
        )
    )
    text = bars.mark_text(align="left", dx=6, font="IBM Plex Mono", fontSize=11, color=T.INK).encode(
        text="label:N"
    )
    perfect = (
        alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(strokeDash=[4, 4], color=T.PERFECT).encode(x="x:Q")
    )
    return (bars + text + perfect).properties(height=40 * len(df) + 20)


def delta_bars(rows: pd.DataFrame) -> alt.LayerChart:
    """Fig 3.2: diverging bars of pnl_delta_gbp around zero, bad red left, good green right."""
    labels = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}
    df = rows[["shift", "pnl_delta_gbp"]].copy()
    df["label"] = df["shift"].map(labels)
    df["text"] = df.pnl_delta_gbp.map(lambda v: "failed" if pd.isna(v) else f"{v:+.2f}")
    df["pnl_delta_gbp"] = df.pnl_delta_gbp.fillna(0.0)
    base = alt.Chart(df).encode(y=alt.Y("label:N", sort=list(labels.values()), title=None))
    bars = base.mark_bar(cornerRadius=3).encode(
        x=alt.X("pnl_delta_gbp:Q", title="£ versus as decided", axis=alt.Axis(tickCount=6)),
        color=alt.condition("datum.pnl_delta_gbp < 0", alt.value(T.BAD), alt.value(T.GOOD)),
        tooltip=["label:N", "pnl_delta_gbp:Q"],
    )
    text = base.mark_text(align="left", dx=4, font="IBM Plex Mono", fontSize=11).encode(
        x=alt.X("pnl_delta_gbp:Q"), text="text:N"
    )
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=T.INK, opacity=0.5).encode(x="x:Q")
    return (bars + text + zero).properties(height=T.SECONDARY_H)


def hold_card(hold) -> None:
    """A hold is a correct decision, not a problem: a serif pull-quote, never a warning box."""
    with st.container(border=True):
        eyebrow("latest hold")
        st.markdown(f"*{hold.reason}*")
        when = f"Held {T.local_naive(hold.target_time):%H:%M}, decided {T.local_naive(hold.decided_at):%H:%M}"
        spread = (
            f" · expected spread £{hold.expected_spread:.2f}/MWh" if hold.expected_spread is not None else ""
        )
        st.caption(f"`{when}{spread}`")
