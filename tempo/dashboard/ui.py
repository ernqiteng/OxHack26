"""Shared screen pieces for the dashboard.

Owner: Ayo. Small helpers so every section is assembled from the same parts: the page stylesheet, a
gradient eyebrow chip + heading, stat cards, banner panels either side of a donut (the layout of a live
grid monitor), figure labels, the price chart with band / now-rule / action glyphs, the 48-period strip,
the backtest ladder and gauge, the delta bars and the hold card.

Styling hooks: bordered-looking cards are `st.container(key="card-…")`, which Streamlit renders with the
class `st-key-card-…`; the stylesheet in `inject_css` gives every such container the white card look.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from tempo.dashboard import theme as T


def gbp(x: float | None, dp: int = 2) -> str:
    return "failed" if x is None or pd.isna(x) else f"£{x:,.{dp}f}"


# -- page stylesheet ---------------------------------------------------------------------------

CSS = f"""
<style>
.stApp {{
  background:
    radial-gradient(1100px 520px at 0% -8%, rgba(29, 83, 159, 0.30), transparent 62%),
    radial-gradient(900px 460px at 100% 0%, rgba(231, 52, 39, 0.24), transparent 60%),
    radial-gradient(800px 420px at 50% 100%, rgba(255, 194, 14, 0.22), transparent 65%),
    linear-gradient(180deg, #f4f5f9 0%, {T.PAGE} 100%);
  background-attachment: fixed;
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ max-width: 1320px; padding-top: 2rem; padding-bottom: 4rem; }}

/* Headings */
h1 {{
  text-align: center; font-size: 3.6rem !important; font-weight: 700 !important; letter-spacing: -0.02em;
  background: {T.GRAD_BRAND}; -webkit-background-clip: text; background-clip: text;
  color: transparent !important;
  padding-bottom: 0 !important;
}}
h3 {{ color: {T.INK} !important; font-weight: 600 !important; letter-spacing: -0.01em; }}
[data-testid="stHeaderActionElements"] {{ display: none; }}

/* Cards: any container keyed card-… */
div[class*="st-key-card"] {{
  background: {T.PAPER}; border: 1px solid {T.BORDER_LIGHT}; border-radius: 16px;
  padding: 1.1rem 1.25rem 1.2rem 1.25rem;
  box-shadow: 0 1px 2px rgba(11, 31, 58, 0.05), 0 10px 28px rgba(11, 31, 58, 0.07);
}}
div[class*="st-key-card"] div[class*="st-key-card"] {{ box-shadow: none; }}
div.st-key-card-selfgrade {{
  background: {T.GRAD_NAVY}; border: none; color: #fff;
}}
div.st-key-card-selfgrade p, div.st-key-card-selfgrade strong {{ color: #fff !important; }}
div[class*="st-key-card-shift"] {{ padding-top: 0; overflow: hidden; }}
div[class*="st-key-card-weak"] {{ border-left: 6px solid {T.HOLD}; height: 100%; }}
div[class*="st-key-card-weak"]:nth-of-type(3n+2) {{ border-left-color: {T.MLH_RED}; }}
div[class*="st-key-donut"] {{ align-items: center; }}
div[class*="st-key-donut"] [data-testid="stVegaLiteChart"] {{ margin: 0 auto; }}
div.st-key-card-gauge {{ height: 100%; }}
div.st-key-card-gauge [data-testid="stCaptionContainer"] {{ text-align: center; }}

/* Stat cards (st.metric) */
[data-testid="stMetric"] {{ text-align: center; }}
[data-testid="stMetricLabel"] {{ justify-content: center; color: {T.INK}; }}
[data-testid="stMetricLabel"] p {{ font-size: 0.98rem !important; white-space: normal; }}
[data-testid="stMetricValue"] * {{
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
}}
[data-testid="stMetricValue"] {{
  justify-content: center; font-weight: 300; color: {T.INK}; font-size: 1.55rem;
}}
[data-testid="stMetricDelta"] {{ justify-content: center; }}
.tp-op {{ text-align: center; font-size: 1.8rem; font-weight: 300; color: {T.INK}; padding-top: 1.6rem; }}

/* Captions and figure labels */
[data-testid="stCaptionContainer"] {{ color: {T.TEXT_SECONDARY}; }}
.tp-fig {{
  font-size: 1.05rem; font-weight: 600; color: {T.INK}; text-align: center; margin: 0.1rem 0 0.2rem 0;
}}
.tp-fig span {{
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 400; color: {T.UNIT};
  letter-spacing: 0.08em; margin-right: 0.45rem;
}}

/* Section eyebrow chips */
.tp-eyebrow {{
  display: inline-block; color: #fff; font-family: 'IBM Plex Mono', monospace; font-size: 0.74rem;
  text-transform: uppercase; letter-spacing: 0.2em; padding: 0.32rem 0.85rem; border-radius: 999px;
  margin: 0.4rem 0 0.1rem 0; box-shadow: 0 4px 14px rgba(11, 31, 58, 0.15);
}}

/* Hero */
.tp-byline {{ text-align: center; color: {T.TEXT_SECONDARY}; font-size: 1.05rem; margin-bottom: -0.6rem; }}
.tp-byline b {{ color: {T.MLH_BLUE}; font-weight: 600; }}
.tp-chip {{
  display: inline-block; margin-left: 0.5rem; padding: 0.12rem 0.75rem; border-radius: 999px;
  background: {T.GRAD_SELL}; color: #fff; font-weight: 600; font-size: 0.92rem;
}}
.tp-tagline {{ text-align: center; color: {T.INK}; font-size: 1.15rem; margin: -0.4rem 0 0.6rem 0; }}
.tp-live {{
  display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%; background: {T.MLH_RED};
  margin-right: 0.45rem; vertical-align: middle; box-shadow: 0 0 0 0 rgba(231, 52, 39, 0.6);
  animation: tp-pulse 1.8s infinite;
}}
@keyframes tp-pulse {{
  0% {{ box-shadow: 0 0 0 0 rgba(231, 52, 39, 0.55); }}
  70% {{ box-shadow: 0 0 0 10px rgba(231, 52, 39, 0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(231, 52, 39, 0); }}
}}
div.st-key-hero [data-testid="stCaptionContainer"], div.st-key-hero [data-testid="stMarkdownContainer"] {{
  text-align: center;
}}
div.st-key-hero a {{ color: {T.MLH_BLUE}; text-decoration: none; font-weight: 600; }}
.tp-status {{ text-align: center; margin: 0.2rem 0 0.4rem 0; }}

/* Banner panels either side of the donut */
.tp-panel {{ background: {T.PAPER}; border-radius: 14px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(11, 31, 58, 0.05), 0 10px 28px rgba(11, 31, 58, 0.07); }}
.tp-banner {{
  display: flex; align-items: baseline; gap: 0.6rem; color: #fff; padding: 0.72rem 1.1rem;
  font-size: 1.08rem; font-weight: 600;
}}
.tp-left .tp-banner {{
  clip-path: polygon(0 0, 100% 0, calc(100% - 26px) 100%, 0 100%); padding-right: 2.2rem;
}}
.tp-right .tp-banner {{ clip-path: polygon(0 0, 100% 0, 100% 100%, 26px 100%); padding-left: 2.2rem;
  flex-direction: row-reverse; }}
.tp-banner .v {{ font-weight: 600; }}
.tp-banner .u {{ font-weight: 400; opacity: 0.72; margin-left: 0.12rem; }}
.tp-banner .name {{ margin-left: auto; }}
.tp-right .tp-banner .name {{ margin-left: 0; margin-right: auto; }}
.tp-row {{
  display: flex; align-items: baseline; gap: 0.6rem; padding: 0.5rem 1.1rem; font-size: 1.02rem;
  color: {T.INK}; border-bottom: 1px solid {T.BORDER_LIGHT};
}}
.tp-right .tp-row {{ flex-direction: row-reverse; }}
.tp-row:last-child {{ border-bottom: none; }}
.tp-row .sw {{ width: 1.5rem; height: 1.5rem; border-radius: 4px; flex: none; align-self: center; }}
.tp-row .v {{ font-weight: 400; }}
.tp-row .u {{ color: {T.UNIT}; margin-left: 0.12rem; }}
.tp-row .n {{ min-width: 6.4rem; }}
.tp-right .tp-row .n {{ text-align: right; }}
.tp-row .name {{ margin-left: auto; color: {T.INK}; }}
.tp-right .tp-row .name {{ margin-left: 0; margin-right: auto; }}

/* Shift cards in the timing audit */
.tp-shift {{
  margin: 0 -1.25rem 0.6rem -1.25rem; padding: 0.6rem 1rem; color: #fff; font-weight: 600;
  text-align: center; font-size: 0.98rem;
}}

/* Weak-point and about cards */
.tp-note {{
  background: {T.PAPER}; border-radius: 14px; padding: 1rem 1.1rem; color: {T.INK}; height: 100%;
  border-left: 6px solid {T.HOLD};
  box-shadow: 0 1px 2px rgba(11, 31, 58, 0.05), 0 10px 28px rgba(11, 31, 58, 0.07);
}}
.tp-box {{ background: {T.PAPER}; border-radius: 14px; overflow: hidden; height: 100%;
  box-shadow: 0 1px 2px rgba(11, 31, 58, 0.05), 0 10px 28px rgba(11, 31, 58, 0.07); }}
.tp-box h4 {{ margin: 0; padding: 0.8rem 1.2rem; color: #fff; font-weight: 600; font-size: 1.15rem; }}
.tp-box .body {{
  padding: 1rem 1.25rem 1.2rem 1.25rem; color: {T.INK}; line-height: 1.6; font-size: 1.02rem;
}}
.tp-box .body li {{ margin-bottom: 0.35rem; }}
.tp-stack {{ display: flex; flex-direction: column; gap: 0.55rem; }}
.tp-stack div {{ color: #fff; border-radius: 10px; padding: 0.6rem 0.9rem; font-weight: 600; }}
.tp-stack div span {{ display: block; font-weight: 400; opacity: 0.85; font-size: 0.9rem; }}
.tp-footer {{ text-align: center; color: {T.TEXT_SECONDARY}; margin-top: 2.5rem; font-size: 0.9rem; }}

/* Widgets */
button[kind="primary"] {{
  background: {T.GRAD_SELL} !important; border: none !important; font-weight: 600 !important;
  box-shadow: 0 6px 18px rgba(231, 52, 39, 0.3);
}}
hr {{ border: none !important; height: 3px !important; border-radius: 3px; opacity: 0.35;
  background: {T.GRAD_BRAND} !important; margin: 2.2rem 0 !important; }}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


# -- text pieces -------------------------------------------------------------------------------


def eyebrow(text: str, grad: str = T.GRAD_NAVY) -> None:
    """Uppercase, letter-spaced section label on a gradient chip."""
    st.html(f'<span class="tp-eyebrow" style="background:{grad}">{escape(text)}</span>')


def section(label: str, sentence: str, anchor: str, grad: str = T.GRAD_NAVY) -> None:
    """Gradient eyebrow chip + heading that is a real sentence with a real number."""
    eyebrow(label, grad)
    st.subheader(sentence, anchor=anchor)


def fig_label(n: str, title: str) -> None:
    st.html(f'<div class="tp-fig"><span>FIG {escape(n)}</span>{escape(title)}</div>')


def status_dot(ok: bool | None, label: str) -> str:
    colour = T.GOOD if ok else (T.QUESTION if ok is None else T.BAD)
    return (
        '<span style="display:inline-flex;align-items:center;gap:0.4rem;margin:0 0.7rem;'
        "padding:0.25rem 0.75rem;border-radius:999px;background:#fff;"
        "box-shadow:0 1px 2px rgba(11,31,58,.06),0 4px 12px rgba(11,31,58,.06);"
        f"font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:{T.INK}\">"
        f'<span style="width:0.55rem;height:0.55rem;border-radius:50%;background:{colour};'
        'display:inline-block"></span>'
        f"{escape(label)}</span>"
    )


def status_strip(items: list[tuple[bool | None, str]]) -> None:
    dots = "".join(status_dot(ok, lbl) for ok, lbl in items)
    st.html(f'<div class="tp-status">{dots}</div>')


def pill(label: str, value: str, help_text: str | None = None, border: bool = False) -> None:
    st.metric(label, value, help=help_text, border=border)


def operator(symbol: str) -> None:
    """The '=' and '−' between stat cards (spread = high − low)."""
    st.html(f'<div class="tp-op">{escape(symbol)}</div>')


def num(value: str, unit: str = "") -> str:
    """A number with its unit in light grey: '£7.87' + '/MWh'."""
    unit_html = f'<span class="u">{escape(unit)}</span>' if unit else ""
    return f'<span class="n"><span class="v">{escape(value)}</span>{unit_html}</span>'


def banner_panel(blocks: list[dict], side: str = "left") -> None:
    """Coloured banner rows with white sub-rows, cut diagonally toward the donut.

    blocks: [{"grad": css, "value": (v, unit), "share": (v, unit) | None, "name": str,
              "rows": [{"colour": css, "value": (v, unit), "name": str}, ...]}, ...]
    """
    parts = [f'<div class="tp-panel tp-{side}">']
    for b in blocks:
        share = num(*b["share"]) if b.get("share") else ""
        parts.append(
            f'<div class="tp-banner" style="background:{b["grad"]}">{num(*b["value"])}{share}'
            f'<span class="name">{escape(b["name"])}</span></div>'
        )
        for r in b.get("rows", []):
            parts.append(
                f'<div class="tp-row"><span class="sw" style="background:{r["colour"]}"></span>'
                f'{num(*r["value"])}<span class="name">{escape(r["name"])}</span></div>'
            )
    parts.append("</div>")
    st.html("".join(parts))


def info_box(title: str, body_html: str, grad: str = T.GRAD_GREY) -> None:
    st.html(
        f'<div class="tp-box"><h4 style="background:{grad}">{escape(title)}</h4>'
        f'<div class="body">{body_html}</div></div>'
    )


def note_card(text: str, colour: str = T.HOLD) -> None:
    st.html(f'<div class="tp-note" style="border-left-color:{colour}">{escape(text)}</div>')


def shift_banner(label: str, grad: str) -> None:
    st.html(f'<div class="tp-shift" style="background:{grad}">{escape(label)}</div>')


# -- charts ------------------------------------------------------------------------------------


def price_chart(
    actual: pd.DataFrame | None,
    forecast: pd.DataFrame | None,
    now: datetime,
    actions: pd.DataFrame | None = None,
    height: int = T.DOMINANT_H,
) -> alt.LayerChart:
    """Fig 1.1: past actual (navy, gradient fill) and future p10-p90 band + p50 (orange), split by the now
    rule, with action glyphs along the bottom. Any of the frames may be empty."""
    layers = []
    if actual is not None and not actual.empty:
        ac = T.localise(actual.rename(columns={"bucket": "t"}), ["t"])
        base = alt.Chart(ac).encode(x=T.time_axis("t"))
        layers.append(
            base.mark_area(
                line=False, color=T.vega_gradient("rgba(29,83,159,0.30)", "rgba(29,83,159,0.0)")
            ).encode(y=alt.Y("price:Q", title="£/MWh"))
        )
        layers.append(
            base.mark_line(color=T.INK, strokeWidth=2.2).encode(
                y=alt.Y("price:Q", title="£/MWh"), tooltip=["t:T", "price:Q"]
            )
        )
    if forecast is not None and not forecast.empty:
        fc = T.localise(forecast.rename(columns={"target_time": "t"}), ["t"])
        base = alt.Chart(fc).encode(x=T.time_axis("t"))
        layers.append(
            base.mark_area(color=T.vega_gradient("rgba(247,147,30,0.38)", "rgba(255,194,14,0.14)")).encode(
                y=alt.Y("p10:Q", title="£/MWh"), y2="p90:Q", tooltip=["t:T", "p10:Q", "p50:Q", "p90:Q"]
            )
        )
        layers.append(
            base.mark_line(color=T.BELIEF, strokeWidth=2.4).encode(y="p50:Q", tooltip=["t:T", "p50:Q"])
        )
    if actions is not None and not actions.empty:
        acts = actions[actions.action != "hold"].rename(columns={"target_time": "t"})
        if not acts.empty:
            acts = T.localise(acts, ["t"]).assign(glyph=lambda d: d.action.map(T.ACTION_GLYPH))
            layers.append(
                alt.Chart(acts)
                .mark_text(size=13, baseline="bottom", dy=-2)
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
    # Quantitative positions throughout: discrete (band) scales collapse inside Streamlit's stretch layout.
    df["x0"], df["x1"], df["mid"] = df.period - 0.5, df.period + 0.5, df.period
    df["y0"], df["y1"], df["ymid"] = 0.0, 1.0, 0.5
    df = T.localise(df, ["t"])
    current = T.local_naive(now)
    df["current"] = (df.t <= current) & (current < df.t + pd.Timedelta(minutes=30))
    n = len(df)
    xscale = alt.Scale(domain=[0.5, n + 0.5], nice=False, zero=False)
    yscale = alt.Scale(domain=[0, 1], nice=False)
    tooltip = ["period:O", "t:T", "label:N", "mw:Q", "expected_spread:Q", "reason:N"]
    base = alt.Chart(df)
    cells = base.mark_rect(cornerRadius=3).encode(
        x=alt.X("x0:Q", scale=xscale, title=None, axis=alt.Axis(values=list(range(1, n + 1, 4)), grid=False)),
        x2="x1:Q",
        y=alt.Y("y0:Q", scale=yscale, axis=None),
        y2="y1:Q",
        tooltip=tooltip,
        color=alt.Color(
            "action:N",
            scale=alt.Scale(domain=list(T.ACTION_COLOUR), range=list(T.ACTION_COLOUR.values())),
            legend=alt.Legend(title=None, orient="top"),
        ),
        stroke=alt.condition("datum.current", alt.value(T.INK), alt.value(T.PAPER)),
        strokeWidth=alt.condition("datum.current", alt.value(2.5), alt.value(1)),
    )
    glyphs = base.mark_text(size=10).encode(
        x=alt.X("mid:Q", scale=xscale),
        y=alt.Y("ymid:Q", scale=yscale),
        text="glyph:N",
        tooltip=tooltip,
        color=alt.condition("datum.action == 'hold'", alt.value(T.INK), alt.value(T.PAPER)),
    )
    return (cells + glyphs).properties(height=T.STRIP_H)


def schedule_donut(sched: pd.DataFrame, size: int = 360) -> alt.LayerChart:
    """The centrepiece: an outer ring of one segment per settlement period (a 24-hour clock face, coloured by
    action) around an inner ring of the totals, with the totals written in the middle."""
    scale = alt.Scale(domain=list(T.ACTION_COLOUR), range=list(T.ACTION_COLOUR.values()))
    df = T.localise(sched.rename(columns={"target_time": "t"}), ["t"]).reset_index(drop=True)
    df["one"] = 1
    df["period"] = range(1, len(df) + 1)
    df["label"] = df.action.map(T.ACTION_LABEL)
    df["clock"] = [f"{t:%H:%M}" if i % 8 == 0 else "" for i, t in enumerate(df.t)]
    totals = df.groupby("action", sort=False).size().rename("n").reset_index()
    totals["label"] = totals.action.map(T.ACTION_LABEL)
    totals["share"] = (100 * totals.n / max(len(df), 1)).round(1)

    r_out, r_in = size * 0.41, size * 0.33
    ring_bg = (
        alt.Chart(pd.DataFrame({"one": [1]}))
        .mark_arc(innerRadius=0, outerRadius=size * 0.485, color="#e4e7ed")
        .encode(theta="one:Q")
    )
    outer = (
        alt.Chart(df)
        .mark_arc(innerRadius=r_in + 6, outerRadius=r_out, stroke="#ffffff", strokeWidth=1.2)
        .encode(
            theta=alt.Theta("one:Q", stack=True),
            order=alt.Order("period:Q"),
            color=alt.Color("action:N", scale=scale, legend=None),
            tooltip=[
                alt.Tooltip("period:O", title="period"),
                alt.Tooltip("t:T", title="time", format="%H:%M"),
                alt.Tooltip("label:N", title="action"),
                alt.Tooltip("mw:Q", title="MW"),
            ],
        )
    )
    inner = (
        alt.Chart(totals)
        .mark_arc(innerRadius=size * 0.23, outerRadius=r_in, stroke="#ffffff", strokeWidth=2, opacity=0.85)
        .encode(
            theta=alt.Theta("n:Q", stack=True),
            color=alt.Color("action:N", scale=scale, legend=None),
            tooltip=[
                alt.Tooltip("label:N", title="action"),
                "n:Q",
                alt.Tooltip("share:Q", title="% of periods"),
            ],
        )
    )
    centre_disc = (
        alt.Chart(pd.DataFrame({"one": [1]}))
        .mark_arc(innerRadius=0, outerRadius=size * 0.23 - 2, color="#ffffff")
        .encode(theta="one:Q")
    )
    trading = int((df.action != "hold").sum())
    mwh = float(df.mw.abs().sum()) * 0.5
    lines = pd.DataFrame(
        {
            "text": ["Schedule", f"{len(df)} periods", f"{trading} trading · {mwh:.1f} MWh"],
            "dy": [-26, 4, 30],
            "size": [15, 22, 13],
            "colour": [T.TEXT_SECONDARY, T.INK, T.TEXT_SECONDARY],
        }
    )
    centre = (
        alt.Chart(lines)
        .mark_text(font="IBM Plex Sans", baseline="middle")
        .encode(
            x=alt.value(size / 2),
            y=alt.value(size / 2),
            text="text:N",
            size=alt.Size("size:Q", scale=None, legend=None),
            color=alt.Color("colour:N", scale=None, legend=None),
            yOffset=alt.YOffset("dy:Q", scale=None),
        )
    )
    clock = (
        alt.Chart(df)
        .mark_text(radius=size * 0.452, font="IBM Plex Mono", fontSize=10, color=T.TEXT_SECONDARY)
        .encode(theta=alt.Theta("one:Q", stack=True), order=alt.Order("period:Q"), text="clock:N")
    )
    return (
        alt.layer(ring_bg, outer, inner, centre_disc, clock, centre)
        .resolve_scale(theta="independent")
        .properties(width=size, height=size)
    )


def gauge(pct: float, label: str, size: int = 230, colour: str = T.MLH_BLUE) -> alt.LayerChart:
    """A single-value ring: pct of 100 filled, the number in the middle."""
    df = pd.DataFrame({"part": ["value", "rest"], "v": [max(pct, 0.0), max(100 - pct, 0.0)]})
    ring = (
        alt.Chart(df)
        .mark_arc(innerRadius=size * 0.33, outerRadius=size * 0.47, cornerRadius=6)
        .encode(
            theta=alt.Theta("v:Q", stack=True),
            order=alt.Order("part:N", sort="descending"),
            color=alt.Color(
                "part:N", scale=alt.Scale(domain=["value", "rest"], range=[colour, "#e4e7ed"]), legend=None
            ),
        )
    )
    lines = pd.DataFrame({"text": [f"{pct:.1f}%", label], "dy": [-8, 20], "size": [30, 13]})
    centre = (
        alt.Chart(lines)
        .mark_text(font="IBM Plex Sans", color=T.INK, baseline="middle")
        .encode(
            x=alt.value(size / 2),
            y=alt.value(size / 2),
            text="text:N",
            size=alt.Size("size:Q", scale=None, legend=None),
            yOffset=alt.YOffset("dy:Q", scale=None),
        )
    )
    return alt.layer(ring, centre).resolve_scale(theta="independent").properties(width=size, height=size)


def ladder(summary: pd.DataFrame, main_prefix: str = "tempo") -> alt.LayerChart:
    """Fig 4.1: horizontal bar ladder of % of perfect; the main strategy in a blue gradient, others grey,
    perfect as a dashed rule at 100."""
    df = summary.copy()
    df["is_main"] = df.strategy.str.lower().str.startswith(main_prefix.lower())
    df["label"] = df.apply(lambda r: f"£{r.pnl_gbp:,.0f}  ·  {r.pct_of_perfect:.1f}%", axis=1)
    order = df.strategy.tolist()
    y = alt.Y("strategy:N", sort=order, title=None, axis=alt.Axis(labelLimit=320, labelFont="IBM Plex Sans"))
    x = alt.X(
        "pct_of_perfect:Q",
        title="% of perfect foresight",
        scale=alt.Scale(domain=[0, 112]),
        axis=alt.Axis(values=[0, 25, 50, 75, 100]),
    )
    tooltip = ["strategy:N", "pnl_gbp:Q", "pct_of_perfect:Q"]
    base = alt.Chart(df).encode(y=y, x=x, tooltip=tooltip)
    others = base.transform_filter("!datum.is_main").mark_bar(cornerRadiusEnd=5, color="#c9ced8")
    main = base.transform_filter("datum.is_main").mark_bar(
        cornerRadiusEnd=5, color=T.vega_gradient(T.MLH_BLUE, T.SKY, x2=1, y2=0)
    )
    text = base.mark_text(align="left", dx=6, font="IBM Plex Mono", fontSize=11, color=T.INK).encode(
        text="label:N"
    )
    perfect = (
        alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(strokeDash=[4, 4], color=T.PERFECT).encode(x="x:Q")
    )
    return (others + main + text + perfect).properties(height=42 * len(df) + 20)


def delta_bars(rows: pd.DataFrame) -> alt.LayerChart:
    """Fig 3.2: diverging bars of pnl_delta_gbp around zero, bad red left, good green right."""
    labels = {-2: "1 h earlier", -1: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later"}
    df = rows[["shift", "pnl_delta_gbp"]].copy()
    df["label"] = df["shift"].map(labels)
    df["text"] = df.pnl_delta_gbp.map(lambda v: "failed" if pd.isna(v) else f"{v:+.2f}")
    df["pnl_delta_gbp"] = df.pnl_delta_gbp.fillna(0.0)
    base = alt.Chart(df).encode(y=alt.Y("label:N", sort=list(labels.values()), title=None))
    bars = base.mark_bar(cornerRadius=4).encode(
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
    """A hold is a correct decision, not a problem: a yellow banner with its reason, never a warning box."""
    when = f"Held {T.local_naive(hold.target_time):%H:%M}, decided {T.local_naive(hold.decided_at):%H:%M}"
    spread = f" · expected spread £{hold.expected_spread:.2f}/MWh" if hold.expected_spread is not None else ""
    st.html(
        f'<div class="tp-box"><h4 style="background:{T.GRAD_HOLD};color:{T.INK}">— Latest hold</h4>'
        f'<div class="body"><em>{escape(str(hold.reason))}</em><br>'
        f'<span style="font-family:IBM Plex Mono,monospace;font-size:0.85rem;color:{T.TEXT_SECONDARY}">'
        f"{escape(when + spread)}</span></div></div>"
    )
