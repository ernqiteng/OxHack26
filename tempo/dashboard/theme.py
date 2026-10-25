"""Colours and the Altair theme for the dashboard.

Owner: Ayo. Every chart in the app is built on these so the eye never re-learns a chart: white cards on a
soft grey page, one axis grammar, UK local time on the x axis, a drawn "now" rule, action glyphs on the
price they react to.

Palette: the hackathon's colours (MLH red, blue and yellow) on HRT-style deep navy ink, laid out like a live
grid monitor (coloured banner rows around a donut, light-weight numbers with grey units). The hex values are
eyeballed approximations, not official brand values.
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd

# Surfaces and ink
PAGE = "#eef0f4"
PAPER = "#ffffff"
PAPER_ELEVATED = "#f6f7fa"
INK = "#0b1f3a"  # deep navy
TEXT_SECONDARY = "#6b7385"
UNIT = "#a3a9b6"  # the grey units after a number ("£7.87/MWh")
BORDER = "#d9dde5"
BORDER_LIGHT = "#e8ebf0"

# Brand
NAVY = INK
MLH_RED = "#e73427"
MLH_BLUE = "#1d539f"
MLH_YELLOW = "#ffc20e"
SKY = "#3d8bfd"
BRAND = MLH_BLUE
BRAND_TINT = "#e5edf8"

# Meaning
CHARGE = MLH_BLUE
DISCHARGE = MLH_RED
HOLD = "#f2a900"  # MLH yellow, one step darker so it reads on white
BELIEF = "#f7931e"  # the forecast: warm orange, distinct from the three actions
PERFECT = "#8a93a6"
GOOD = "#1f9d55"
BAD = MLH_RED
QUESTION = "#c27c00"

ACTION_COLOUR = {"charge": CHARGE, "discharge": DISCHARGE, "hold": HOLD}
ACTION_GLYPH = {"charge": "▲", "discharge": "▼", "hold": "—"}
ACTION_LABEL = {"charge": "charge", "discharge": "sell", "hold": "hold"}

# Banner gradients, one per meaning (CSS)
GRAD_CHARGE = f"linear-gradient(100deg, {MLH_BLUE} 0%, {SKY} 100%)"
GRAD_SELL = f"linear-gradient(100deg, {MLH_RED} 0%, #ff7a45 100%)"
GRAD_HOLD = f"linear-gradient(100deg, {HOLD} 0%, {MLH_YELLOW} 100%)"
GRAD_NAVY = f"linear-gradient(100deg, {NAVY} 0%, #23407a 100%)"
GRAD_FORECAST = f"linear-gradient(100deg, #e36f00 0%, {BELIEF} 100%)"
GRAD_GREY = "linear-gradient(100deg, #8d95a5 0%, #b3b9c5 100%)"
GRAD_BRAND = f"linear-gradient(90deg, {NAVY} 0%, {MLH_BLUE} 45%, {MLH_RED} 80%, {MLH_YELLOW} 100%)"


def vega_gradient(top: str, bottom: str, x2: float = 0, y2: float = 1) -> dict:
    """A Vega-Lite linear gradient for mark fills (vertical by default)."""
    return {
        "gradient": "linear",
        "x1": 0,
        "y1": 0,
        "x2": x2,
        "y2": y2,
        "stops": [{"offset": 0, "color": top}, {"offset": 1, "color": bottom}],
    }


LONDON = "Europe/London"
DOMINANT_H, SECONDARY_H, STRIP_H = 320, 190, 56


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
                "labelFont": "IBM Plex Sans",
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
                "symbolType": "circle",
            },
            "title": {
                "color": INK,
                "font": "IBM Plex Sans",
                "fontSize": 15,
                "fontWeight": 600,
                "anchor": "middle",
            },
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
    rule = (
        alt.Chart(df)
        .mark_rule(color=MLH_RED, opacity=0.8, strokeWidth=1.5, strokeDash=[3, 3])
        .encode(x="t:T")
    )
    text = (
        alt.Chart(df)
        .mark_text(
            align="left",
            dx=4,
            dy=-4,
            baseline="bottom",
            color=MLH_RED,
            font="IBM Plex Mono",
            fontSize=11,
        )
        .encode(x="t:T", text="label:N", y=alt.value(0))
    )
    return rule + text
