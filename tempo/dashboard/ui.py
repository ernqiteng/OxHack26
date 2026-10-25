"""Shared screen pieces for the dashboard, in the style of grid.iamkate.com (National Grid: Live).

Owner: Ayo. Every section is assembled from the same parts: the page stylesheet, #222 panels with a #444
header strip, the two KPI panels, the plan wheel (a 24-hour clock of today's 48 settlement periods with a
price ring inside it and the plan's blocks tabled on either side), the price chart with band / now rule /
action glyphs, the 48-period strip, the backtest ladder, the delta bars, the hold card and the status pills.
"""

from __future__ import annotations

import html
import math
from datetime import datetime
from typing import Any

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from tempo.dashboard import theme as T

esc = html.escape


def gbp(x: float | None, dp: int = 2) -> str:
    return "failed" if x is None or pd.isna(x) else f"£{x:,.{dp}f}"


# -- page chrome -------------------------------------------------------------------------------

CSS = f"""
<style>
.stApp {{ background: {T.BACKGROUND}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.stAppDeployButton {{ display: none; }}
.block-container {{ max-width: 1800px; padding: 1.25rem 2rem 4rem; }}
h1, h2, h3 {{ font-weight: 400 !important; letter-spacing: 0; }}
a {{ text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* hero */
.st-key-hero {{ text-align: center; gap: .5rem; }}
.st-key-hero [data-testid="stHeadingWithActionElements"], .st-key-hero h1 {{ display: block; width: 100%;
  text-align: center; padding: 0; margin: .25rem 0 0; }}
.st-key-hero [data-testid="stMarkdownContainer"] {{ text-align: center; margin: 0 auto; max-width: 62rem; }}
.st-key-hero [data-testid="stMarkdownContainer"] p {{ font-size: 1.25rem; color: {T.INK}; }}
.st-key-hero [data-testid="stCaptionContainer"] {{ text-align: center; max-width: none; }}
.st-key-hero [data-testid="stCaptionContainer"] p {{ font-size: 1rem; color: {T.TEXT_SECONDARY}; }}
.tempo-top {{ font-size: 1.15rem; color: {T.INK}; display: flex; gap: .6rem; justify-content: center;
  align-items: center; flex-wrap: wrap; }}
.tempo-top a {{ color: {T.ACCENT}; }}
.pill {{ display: inline-flex; align-items: center; gap: .4rem; background: {T.HEAD}; color: #fff;
  border-radius: 1rem; padding: .15rem .8rem; font-size: 1rem; white-space: nowrap; }}
.dot {{ width: .6rem; height: .6rem; border-radius: 50%; display: inline-block; }}

/* section nav, styled like the site's range tabs */
.tempo-tabs {{ display: flex; background: {T.HEAD}; border-radius: .75rem; overflow: hidden; }}
.tempo-tabs a {{ flex: 1; text-align: center; padding: .8rem 1rem; font-size: 1.5rem; color: #fff; }}
.tempo-tabs a:hover {{ background: {T.PANEL}; text-decoration: none; }}

/* KPI panels */
.tempo-kpi {{ background: {T.PANEL}; border-radius: .75rem; padding: 1.1rem 1rem; display: flex;
  align-items: center; justify-content: space-evenly; text-align: center; gap: .5rem; min-height: 7.2rem; }}
.tempo-kpi .label {{ font-size: 1.15rem; color: {T.INK}; margin-bottom: .35rem; white-space: nowrap; }}
.tempo-kpi .value {{ font-size: 1.6rem; color: {T.INK}; font-variant-numeric: tabular-nums;
  white-space: nowrap; }}
.tempo-kpi .op {{ font-size: 1.6rem; color: {T.TEXT_SECONDARY}; padding-top: 1.4rem; }}
.u {{ opacity: .6; margin-left: .08em; }}
.help {{ display: inline-block; width: 1.15em; height: 1.15em; line-height: 1.15em; border-radius: 50%;
  background: {T.HEAD}; color: #fff; font-size: .7em; text-align: center; vertical-align: .15em;
  margin-left: .35em; cursor: help; font-weight: 500; }}

/* panels: a keyed st.container with a header strip as its first child */
[class*="st-key-panel-"] {{ background: {T.PANEL}; border-radius: .75rem; padding: 0 1rem 1rem; }}
.tempo-head {{ background: {T.HEAD}; color: #fff; font-size: 1.5rem; padding: .7rem 1rem;
  margin: 0 -1rem; border-radius: .75rem .75rem 0 0; display: flex; justify-content: space-between;
  align-items: baseline; gap: 1rem; }}
.tempo-head small {{ font-size: 1rem; color: #ddd; }}
[class*="st-key-panel-"] h3 {{ padding: 0; margin: 0; }}
[class*="st-key-panel-"] [data-testid="stCaptionContainer"] p {{ color: {T.TEXT_SECONDARY}; }}
[class*="st-key-panel-"] [data-baseweb="select"] > div,
[class*="st-key-panel-"] [data-baseweb="input"] > div {{ background: #333; }}
[class*="st-key-panel-"] [data-testid="stMetric"] {{ background: transparent; }}
[class*="st-key-panel-"] [data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {T.HEAD}; }}
[class*="st-key-panel-"] hr {{ border-color: {T.HEAD}; }}
.tempo-prose p, .tempo-prose li {{ font-size: 1.1rem; line-height: 1.55; }}
.tempo-prose a {{ color: {T.ACCENT}; }}
.tempo-prose table {{ margin: .75rem auto; border-collapse: separate; border-spacing: 0 2px; }}
.tempo-prose th {{ text-align: left; padding: .2rem .8rem; font-weight: 500; }}
.tempo-prose td {{ background: {T.STRIPE}; padding: .3rem .8rem; }}

/* the plan wheel */
.tempo-wheel {{ display: grid; grid-template-columns: minmax(0, 1fr) max-content minmax(0, 1fr);
  align-items: center; background: {T.PANEL}; border-radius: .75rem; }}
.tempo-wheel .side {{ align-self: start; min-width: 0; overflow: hidden; }}
.tempo-wheel .centre {{ border-radius: 50%; background: {T.BACKGROUND}; border: 2rem solid {T.BACKGROUND};
  margin: -1rem -2.5rem; z-index: 1; line-height: 0; }}
.tempo-wheel .centre svg {{ width: 430px; max-width: 100%; height: auto; display: block; }}
.tempo-wheel table {{ border-collapse: separate; border-spacing: 0; width: 100%; font-size: 1rem; }}
.tempo-wheel td {{ padding: .35rem .4rem; white-space: nowrap; vertical-align: middle; color: {T.INK}; }}
.tempo-wheel tr.band td {{ font-size: 1.2rem; color: #fff; padding: .7rem .5rem; }}
.tempo-wheel .left tr.band td:first-child {{ padding-left: 1rem; }}
.tempo-wheel .left tr:first-child td:first-child {{ border-top-left-radius: .75rem; }}
.tempo-wheel .right tr:first-child td:last-child {{ border-top-right-radius: .75rem; }}
.tempo-wheel .left td.icon {{ padding-left: 1rem; width: 36px; line-height: 0; }}
.tempo-wheel .left td.v, .tempo-wheel .left td.p {{ text-align: right; font-variant-numeric: tabular-nums; }}
.tempo-wheel .left td.n {{ text-align: left; width: 100%; padding-right: 3.5rem; }}
.tempo-wheel .right td.n {{ text-align: right; width: 100%; padding-left: 2.5rem; }}
.tempo-wheel .right td.p, .tempo-wheel .right td.v {{ text-align: right;
  font-variant-numeric: tabular-nums; }}
.tempo-wheel .right td.s {{ width: 60px; line-height: 0; padding-right: 1rem; }}
.tempo-wheel .right tr.band td:last-child {{ padding-right: 1rem; }}
.tempo-wheel .more {{ color: {T.TEXT_SECONDARY}; font-size: .95rem; }}
@media (max-width: 1100px) {{
  .tempo-wheel {{ grid-template-columns: 1fr; }}
  .tempo-wheel .centre {{ margin: 0 auto; }}
  .tempo-wheel .left td.n {{ padding-right: .5rem; }}
  .tempo-wheel .right td.n {{ padding-left: .5rem; }}
}}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


def help_badge(text: str | None) -> str:
    return f'<span class="help" title="{esc(text)}">?</span>' if text else ""


def unit(value: str, u: str = "") -> str:
    return f'{esc(value)}<span class="u">{esc(u)}</span>' if u else esc(value)


def panel(key: str):
    """A #222 panel. Use as `with ui.panel("live"):` then call panel_head first."""
    return st.container(key=f"panel-{key}")


def panel_head(label: str, aside: str | None = None, anchor: str | None = None) -> None:
    aside_html = f"<small>{esc(aside)}</small>" if aside else ""
    anchor_attr = f' id="{esc(anchor)}-head"' if anchor else ""
    st.html(f'<div class="tempo-head"{anchor_attr}><span>{esc(label)}</span>{aside_html}</div>')


def section(label: str, sentence: str, anchor: str, aside: str | None = None) -> None:
    """Header strip + the section's sentence (a real sentence with a real number) as the h3 anchor."""
    panel_head(label, aside, anchor)
    st.subheader(sentence, anchor=anchor)


def fig_label(n: str, title: str) -> None:
    st.caption(f"Fig {n} · {title}")


def eyebrow(text: str) -> None:
    st.html(f'<div style="font-size:1.2rem;color:{T.INK};margin:.25rem 0 0">{esc(text)}</div>')


def nav_tabs(sections: list[tuple[str, str]]) -> None:
    links = "".join(f'<a href="#{esc(a)}">{esc(label)}</a>' for a, label in sections)
    st.html(f'<div class="tempo-tabs">{links}</div>')


def status_pill(ok: bool | None, label: str) -> str:
    colour = T.GOOD if ok else (T.QUESTION if ok is None else T.BAD)
    return f'<span class="pill"><span class="dot" style="background:{colour}"></span>{esc(label)}</span>'


def top_line(lead: str, items: list[tuple[bool | None, str]]) -> None:
    pills = "".join(status_pill(ok, lbl) for ok, lbl in items)
    st.html(f'<div class="tempo-top"><span>{lead}</span>{pills}</div>')


def status_strip(items: list[tuple[bool | None, str]]) -> None:
    top_line("", items)


def kpi_panel(cells: list[dict[str, Any]], ops: list[str] | None = None) -> None:
    """A row of label-over-value cells, like the site's Time / Price / Emissions panel. `ops` puts an
    operator between cells (Demand = Generation − Transfers)."""
    parts = []
    for i, c in enumerate(cells):
        if ops and i:
            parts.append(f'<div class="op">{esc(ops[i - 1])}</div>')
        value = c.get("html") or unit(str(c.get("value", "—")), c.get("unit", ""))
        parts.append(
            f'<div class="cell"><div class="label">{esc(c["label"])}{help_badge(c.get("help"))}</div>'
            f'<div class="value">{value}</div></div>'
        )
    st.html(f'<div class="tempo-kpi">{"".join(parts)}</div>')


def pill(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text, border=True)


# -- small SVGs --------------------------------------------------------------------------------


def spark(values, colour: str, w: int = 56, h: int = 22, title: str | None = None) -> str:
    v = np.asarray([x for x in values if x is not None and not pd.isna(x)], dtype=float)
    if v.size < 2:
        return ""
    lo, hi = float(v.min()), float(v.max())
    span = hi - lo or 1.0
    xs = np.linspace(1, w - 1, v.size)
    ys = h - 2 - (v - lo) / span * (h - 4)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    t = f"<title>{esc(title)}</title>" if title else ""
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{t}'
        f'<polyline fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round" points="{pts}"/>'
        "</svg>"
    )


def mini_area(values, colour: str, w: int = 30, h: int = 24) -> str:
    """The little filled silhouette the site draws beside each source: here the forecast over a block."""
    v = np.asarray([x for x in values if x is not None and not pd.isna(x)], dtype=float)
    if v.size < 2:
        return f'<svg width="{w}" height="{h}"><rect width="{w}" height="{h}" rx="2" fill="{colour}"/></svg>'
    lo, hi = float(v.min()), float(v.max())
    span = hi - lo or 1.0
    xs = np.linspace(0, w, v.size)
    ys = h - 4 - (v - lo) / span * (h - 10)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" rx="2" '
        f'fill="{colour}" opacity=".35"/><polygon fill="{colour}" points="0,{h} {pts} {w},{h}"/></svg>'
    )


def meter(frac: float, colour: str, w: int = 56, h: int = 10) -> str:
    frac = 0.0 if pd.isna(frac) else min(1.0, max(0.0, float(frac)))
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" rx="3" '
        f'fill="{T.HEAD}"/><rect width="{max(2.0, w * frac):.1f}" height="{h}" rx="3" fill="{colour}"/></svg>'
    )


def _arc(cx: float, cy: float, r0: float, r1: float, a0: float, a1: float) -> str:
    """Annular sector path from angle a0 to a1 (degrees clockwise from 12 o'clock)."""

    def pt(r: float, a: float) -> tuple[float, float]:
        t = math.radians(a - 90)
        return cx + r * math.cos(t), cy + r * math.sin(t)

    large = 1 if (a1 - a0) % 360 > 180 else 0
    x0, y0 = pt(r1, a0)
    x1, y1 = pt(r1, a1)
    x2, y2 = pt(r0, a1)
    x3, y3 = pt(r0, a0)
    return (
        f"M{x0:.1f},{y0:.1f}A{r1},{r1} 0 {large} 1 {x1:.1f},{y1:.1f}"
        f"L{x2:.1f},{y2:.1f}A{r0},{r0} 0 {large} 0 {x3:.1f},{y3:.1f}Z"
    )


# -- the plan wheel ----------------------------------------------------------------------------


def plan_periods(sched: pd.DataFrame, forecast: pd.DataFrame | None) -> pd.DataFrame:
    """One row per settlement period of the next 24 h with local time, action, mw, p50 and reason. With no
    schedule yet, the forecast's periods are shown as holds so the wheel still turns."""
    if sched is None or sched.empty:
        if forecast is None or forecast.empty:
            return pd.DataFrame(columns=["t", "action", "mw", "p50", "reason", "expected_spread"])
        df = forecast[["target_time", "p50"]].copy()
        df["action"], df["mw"], df["reason"], df["expected_spread"] = "hold", 0.0, "", np.nan
    else:
        df = sched.copy()
        if forecast is not None and not forecast.empty and "p50" not in df:
            df = df.merge(forecast[["target_time", "p50"]], on="target_time", how="left")
        if "p50" not in df:
            df["p50"] = np.nan
        for col in ("reason", "expected_spread"):
            if col not in df:
                df[col] = "" if col == "reason" else np.nan
    df = df.rename(columns={"target_time": "t"}).sort_values("t").head(48)
    df = T.localise(df, ["t"]).reset_index(drop=True)
    df["reason"] = df.reason.fillna("")
    return df[["t", "action", "mw", "p50", "reason", "expected_spread"]]


def plan_runs(periods: pd.DataFrame) -> list[dict[str, Any]]:
    """Contiguous blocks of the same action, in time order."""
    runs: list[dict[str, Any]] = []
    for _, r in periods.iterrows():
        if runs and runs[-1]["action"] == r.action and runs[-1]["end"] == r.t:
            run = runs[-1]
            run["end"] = r.t + pd.Timedelta(minutes=30)
            run["n"] += 1
            run["mwh"] += abs(float(r.mw)) * 0.5
            run["p50"].append(r.p50)
            if r.reason and r.reason not in run["reasons"]:
                run["reasons"].append(r.reason)
        else:
            runs.append(
                {
                    "action": r.action,
                    "start": r.t,
                    "end": r.t + pd.Timedelta(minutes=30),
                    "n": 1,
                    "mwh": abs(float(r.mw)) * 0.5,
                    "p50": [r.p50],
                    "reasons": [r.reason] if r.reason else [],
                }
            )
    return runs


def _span(run: dict[str, Any]) -> str:
    return f"{run['start']:%H:%M}–{run['end']:%H:%M}"


def _left_table(periods: pd.DataFrame, runs: list[dict[str, Any]]) -> str:
    """Charge / Sell / Hold bands, each followed by its blocks: icon, MWh, share of the day, time span."""
    n_total = max(1, len(periods))
    rows: list[str] = []
    for action in ("charge", "discharge", "hold"):
        mine = [r for r in runs if r["action"] == action]
        n = sum(r["n"] for r in mine)
        mwh = sum(r["mwh"] for r in mine)
        name = T.ACTION_LABEL[action].capitalize()
        rows.append(
            f'<tr class="band" style="background:{T.ACTION_BAND[action]}">'
            f'<td colspan="2" class="v">{unit(f"{mwh:.1f}", "MWh")}</td>'
            f'<td class="p">{100 * n / n_total:.1f}%</td>'
            f'<td class="n">{T.ACTION_GLYPH[action]} {esc(name)}</td></tr>'
        )
        shown = mine[:5]
        for r in shown:
            p50 = [p for p in r["p50"] if not pd.isna(p)]
            mean = f"mean forecast £{np.mean(p50):.0f}/MWh" if p50 else "no forecast"
            why = "; ".join(r["reasons"]) if r["reasons"] else ""
            tip = f"{_span(r)} · {r['n']} period{'s' if r['n'] != 1 else ''} · {mean}" + (
                f" · {why}" if why else ""
            )
            mwh_cell = unit(f"{r['mwh']:.1f}", "MWh")
            rows.append(
                f'<tr><td class="icon">{mini_area(r["p50"], T.ACTION_COLOUR[action])}</td>'
                f'<td class="v">{mwh_cell}</td>'
                f'<td class="p">{100 * r["n"] / n_total:.1f}%</td>'
                f'<td class="n">{esc(_span(r))}{help_badge(tip)}</td></tr>'
            )
        if len(mine) > len(shown):
            rest = len(mine) - len(shown)
            rows.append(
                f'<tr><td></td><td colspan="3" class="n more">+{rest} more {name.lower()} blocks</td></tr>'
            )
    return f'<table class="left">{"".join(rows)}</table>'


def _right_table(market: list[dict[str, Any]], battery: list[dict[str, Any]], heads: dict[str, str]) -> str:
    """Market and Battery bands; rows are name ? | aux | value | sparkline, like the Interconnectors list."""

    def band(name: str, summary: str) -> str:
        return (
            f'<tr class="band" style="background:{T.HEAD}"><td class="n">{esc(name)}</td>'
            f'<td colspan="3" class="v">{summary}</td></tr>'
        )

    def row(r: dict[str, Any]) -> str:
        return (
            f'<tr><td class="n">{esc(r["name"])}{help_badge(r.get("help"))}</td>'
            f'<td class="p">{r.get("aux", "")}</td><td class="v">{r["value"]}</td>'
            f'<td class="s">{r.get("spark", "")}</td></tr>'
        )

    rows = [band("Market", heads["market"])] + [row(r) for r in market]
    rows += [band("Battery", heads["battery"])] + [row(r) for r in battery]
    return f'<table class="right">{"".join(rows)}</table>'


def wheel_svg(periods: pd.DataFrame, now_local: datetime, centre: dict[str, str], size: int = 500) -> str:
    """Two rings on a 24-hour clock (00:00 at the top): outer = the plan per period, inner = forecast p50
    per period on a one-hue ramp. The current period is outlined. Each sector carries a tooltip."""
    c = size / 2
    r_out = (c - 84, c - 36)  # outer ring
    r_in = (c - 142, c - 88)  # inner ring
    parts = [
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Today\'s plan on a 24-hour clock">',
        '<defs><linearGradient id="tempo-ramp" x1="0" x2="1">'
        + "".join(f'<stop offset="{i / 3:.2f}" stop-color="{T.ramp(i / 3)}"/>' for i in range(4))
        + "</linearGradient></defs>",
        f'<circle cx="{c}" cy="{c}" r="{r_out[1] + 1}" fill="{T.PANEL}" opacity="0"/>',
    ]
    p50 = periods.p50.astype(float) if not periods.empty else pd.Series(dtype=float)
    lo, hi = (float(p50.min()), float(p50.max())) if p50.notna().any() else (0.0, 1.0)
    span = hi - lo or 1.0
    now_min = now_local.hour * 60 + now_local.minute
    current: list[str] = []
    for _, r in periods.iterrows():
        a0 = (r.t.hour * 60 + r.t.minute) / 1440 * 360
        a1 = a0 + 7.5
        label = T.ACTION_LABEL[r.action]
        glyph = T.ACTION_GLYPH[r.action]
        price = "" if pd.isna(r.p50) else f" · forecast £{r.p50:.1f}/MWh"
        mw = f" {abs(float(r.mw)):.0f} MW" if r.action != "hold" else ""
        why = f" · {r.reason}" if r.reason else ""
        tip = esc(f"{r.t:%H:%M}–{(r.t + pd.Timedelta(minutes=30)):%H:%M} · {glyph} {label}{mw}{price}{why}")
        fill = T.ACTION_COLOUR[r.action] if r.action != "hold" else T.HOLD_DIM
        parts.append(
            f'<path d="{_arc(c, c, *r_out, a0, a1)}" fill="{fill}" stroke="{T.BACKGROUND}" '
            f'stroke-width="1.5"><title>{tip}</title></path>'
        )
        inner = T.ramp((r.p50 - lo) / span) if not pd.isna(r.p50) else "#2a2a2a"
        parts.append(
            f'<path d="{_arc(c, c, *r_in, a0, a1)}" fill="{inner}" stroke="{T.BACKGROUND}" '
            f'stroke-width="1.5"><title>{tip}</title></path>'
        )
        start_min = r.t.hour * 60 + r.t.minute
        if start_min <= now_min < start_min + 30:
            current.append(
                f'<path d="{_arc(c, c, r_in[0], r_out[1], a0, a1)}" fill="none" stroke="#fff" '
                'stroke-width="2.5"><title>now</title></path>'
            )
    parts += current
    # hour marks
    for ang, text in ((0, "00:00"), (90, "06:00"), (180, "12:00"), (270, "18:00")):
        t = math.radians(ang - 90)
        x, y = c + (c - 2) * math.cos(t), c + (c - 2) * math.sin(t)
        anchor = "middle" if ang in (0, 180) else ("end" if ang == 90 else "start")
        dy = 11 if ang == 0 else (-3 if ang == 180 else 4)
        dx = 0
        parts.append(
            f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}" fill="{T.TEXT_SECONDARY}" '
            f'font-size="12" font-family="{T.FONT}">{text}</text>'
        )
    # centre
    parts.append(
        f'<text x="{c}" y="{c - 46}" text-anchor="middle" fill="{T.INK}" font-size="21" '
        f'font-family="{T.FONT}">{esc(centre["title"])}</text>'
        f'<line x1="{c - 70}" x2="{c + 70}" y1="{c - 32}" y2="{c - 32}" stroke="{T.TEXT_SECONDARY}"/>'
        f'<text x="{c}" y="{c + 2}" text-anchor="middle" fill="{T.INK}" font-size="27" '
        f'font-family="{T.FONT}">{esc(centre["value"])}</text>'
        f'<text x="{c}" y="{c + 30}" text-anchor="middle" fill="{T.INK}" font-size="19" '
        f'font-family="{T.FONT}">{esc(centre["sub"])}</text>'
        f'<text x="{c}" y="{c + 66}" text-anchor="middle" fill="{T.TEXT_SECONDARY}" font-size="11" '
        f'font-family="{T.FONT}">inner ring: forecast £/MWh</text>'
        f'<rect x="{c - 40}" y="{c + 74}" width="80" height="6" rx="3" fill="url(#tempo-ramp)"/>'
        f'<text x="{c - 46}" y="{c + 80}" text-anchor="end" fill="{T.TEXT_SECONDARY}" font-size="11" '
        f'font-family="{T.FONT}">£{lo:.0f}</text>'
        f'<text x="{c + 46}" y="{c + 80}" text-anchor="start" fill="{T.TEXT_SECONDARY}" font-size="11" '
        f'font-family="{T.FONT}">£{hi:.0f}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def plan_wheel(
    periods: pd.DataFrame,
    now_local: datetime,
    centre: dict[str, str],
    market: list[dict[str, Any]],
    battery: list[dict[str, Any]],
    heads: dict[str, str],
) -> None:
    runs = plan_runs(periods)
    # st.markdown, not st.html: st.html's sanitiser strips inline SVG, which the wheel and sparklines are.
    # One line, no blank lines, so Markdown treats the whole thing as a single HTML block.
    st.markdown(
        '<div class="tempo-wheel">'
        f'<div class="side">{_left_table(periods, runs)}</div>'
        f'<div class="centre">{wheel_svg(periods, now_local, centre)}</div>'
        f'<div class="side">{_right_table(market, battery, heads)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


# -- charts ------------------------------------------------------------------------------------


def price_chart(
    actual: pd.DataFrame | None,
    forecast: pd.DataFrame | None,
    now: datetime,
    actions: pd.DataFrame | None = None,
    height: int = T.DOMINANT_H,
) -> alt.LayerChart:
    """Fig 1.1: past actual (white) and future p10-p90 band + p50 (blue), split by the now rule, with
    action glyphs along the bottom. Any of the frames may be empty."""
    layers = []
    if forecast is not None and not forecast.empty:
        fc = T.localise(forecast.rename(columns={"target_time": "t"}), ["t"])
        base = alt.Chart(fc).encode(x=T.time_axis("t"))
        layers.append(
            base.mark_area(color=T.BELIEF, opacity=0.22).encode(
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
            .mark_line(color=T.ACTUAL, strokeWidth=2)
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
        stroke=alt.condition("datum.current", alt.value("#ffffff"), alt.value(T.PANEL)),
        strokeWidth=alt.condition("datum.current", alt.value(2), alt.value(1)),
    )
    glyphs = base.mark_text(color=T.BACKGROUND, size=9).encode(text="glyph:N")
    return (cells + glyphs).properties(height=T.STRIP_H)


def ladder(summary: pd.DataFrame, main_prefix: str = "tempo") -> alt.LayerChart:
    """Fig 4.1: horizontal bar ladder of % of perfect; the main strategy in brand green, others grey,
    perfect as a dashed rule at 100."""
    df = summary.copy()
    df["is_main"] = df.strategy.str.lower().str.startswith(main_prefix.lower())
    df["label"] = df.apply(lambda r: f"£{r.pnl_gbp:,.0f}  ·  {r.pct_of_perfect:.1f}%", axis=1)
    order = df.strategy.tolist()
    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("strategy:N", sort=order, title=None, axis=alt.Axis(labelLimit=320, labelFont=T.FONT)),
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
    text = bars.mark_text(align="left", dx=6, font=T.MONO, fontSize=11, color=T.INK).encode(text="label:N")
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
    text = base.mark_text(align="left", dx=4, font=T.MONO, fontSize=11, color=T.INK).encode(
        x=alt.X("pnl_delta_gbp:Q"), text="text:N"
    )
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=T.INK, opacity=0.5).encode(x="x:Q")
    return (bars + text + zero).properties(height=T.SECONDARY_H)


def hold_card(hold) -> None:
    """A hold is a correct decision, not a problem: a pull-quote, never a warning box."""
    with st.container(border=True):
        eyebrow("Latest hold")
        st.markdown(f"*{hold.reason}*")
        when = f"Held {T.local_naive(hold.target_time):%H:%M}, decided {T.local_naive(hold.decided_at):%H:%M}"
        spread = (
            f" · expected spread £{hold.expected_spread:.2f}/MWh" if hold.expected_spread is not None else ""
        )
        st.caption(f"{when}{spread}")
