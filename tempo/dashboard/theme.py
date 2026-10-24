"""Colours and the Altair theme for the dashboard (docs/ui-plan.md section 5.2, docs/ui.md section 3.4).

Owner: Ayo. Every chart in the app is built on these so the eye never re-learns a chart: paper background,
one axis grammar, UK local time on the x axis, a drawn "now" rule, action glyphs on the price they react to.
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd

PAPER = "#fafaf8"
PAPER_ELEVATED = "#f5f5f0"
INK = "#1c1917"
TEXT_SECONDARY = "#78716c"
BORDER = "#d6d3d1"
BORDER_LIGHT = "#e7e5e4"
BRAND = "#1a4d3e"
BRAND_TINT = "#e6f0ec"

CHARGE = "#1f8a5a"
DISCHARGE = "#c2410c"
HOLD = "#a8a29e"
BELIEF = "#2563eb"
PERFECT = "#78716c"
GOOD = "#15803d"
BAD = "#991b1b"
QUESTION = "#92400e"

ACTION_COLOUR = {"charge": CHARGE, "discharge": DISCHARGE, "hold": HOLD}
ACTION_GLYPH = {"charge": "▲", "discharge": "▼", "hold": "—"}
ACTION_LABEL = {"charge": "charge", "discharge": "sell", "hold": "hold"}

LONDON = "Europe/London"
DOMINANT_H, SECONDARY_H, STRIP_H = 320, 180, 56


@alt.theme.register("tempo", enable=True)
def tempo_theme() -> alt.theme.ThemeConfig:
    return {
        "config": {
            "background": "transparent",
            "view": {"stroke": None},
            "font": "IBM Plex Sans",
            "axis": {
                "domain": False,
                "gridColor": BORDER_LIGHT,
                "tickColor": BORDER_LIGHT,
                "labelColor": TEXT_SECONDARY,
                "labelFont": "IBM Plex Mono",
                "labelFontSize": 11,
                "titleColor": TEXT_SECONDARY,
                "titleFont": "IBM Plex Sans",
                "titleFontSize": 12,
                "titleFontWeight": 400,
            },
            "legend": {
                "labelColor": INK,
                "labelFont": "IBM Plex Sans",
                "titleColor": TEXT_SECONDARY,
                "orient": "top",
                "symbolType": "stroke",
            },
            "title": {"color": INK, "font": "Libre Baskerville", "fontSize": 14, "anchor": "start"},
            "range": {"category": [CHARGE, DISCHARGE, BELIEF, HOLD]},
        }
    }


def time_axis(field: str, title: str = "") -> alt.X:
    """Every time axis is local UK time with the same formatting."""
    return alt.X(
        f"{field}:T",
        title=title,
        axis=alt.Axis(format="%H:%M", labelAngle=0, tickCount=8),
        scale=alt.Scale(padding=0),
    )


def localise(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Vega renders timestamps in the browser's zone; strip tz after converting to London so the chart
    shows UK clock time whatever the viewer's machine is set to."""
    out = df.copy()
    for c in cols:
        if c in out and getattr(out[c].dt, "tz", None) is not None:
            out[c] = out[c].dt.tz_convert(LONDON).dt.tz_localize(None)
    return out


def local_naive(ts: datetime) -> datetime:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(LONDON).tz_localize(None)
    return ts.to_pydatetime()


def now_rule(ts: datetime, label: str = "now") -> alt.LayerChart:
    df = pd.DataFrame({"t": [local_naive(ts)], "label": [label]})
    rule = alt.Chart(df).mark_rule(color=INK, opacity=0.5, strokeWidth=1).encode(x="t:T")
    text = (
        alt.Chart(df)
        .mark_text(
            align="left",
            dx=4,
            dy=-4,
            baseline="bottom",
            color=TEXT_SECONDARY,
            font="IBM Plex Mono",
            fontSize=11,
        )
        .encode(x="t:T", text="label:N", y=alt.value(0))
    )
    return rule + text
