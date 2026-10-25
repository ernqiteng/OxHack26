"""Colours and the Altair theme for the dashboard, in the style of grid.iamkate.com (National Grid: Live).

Owner: Ayo. Tokens copied from that site's dark theme (CC0): page #111, panel #222, header strip #444, text
#eee, green accent. Chart marks keep Tempo's semantics (charge green, sell orange, forecast blue, hold grey,
the actual price in white) so every chart on the page is read the same way: one axis grammar, UK local time
on the x axis, a drawn "now" rule, action glyphs on the price they react to.

Palette check (dataviz validator, surface #222): charge/sell/forecast pass chroma, contrast and the
normal-vision floor; charge vs sell sits in the 6-8 CVD band, which is why charge and sell always carry
their glyph (▲ ▼) and label and never rely on colour alone. Hold is deliberately grey and always labelled.
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd

# Surfaces and text (grid.css variables: --background, --content-background, --heading-background ...)
BACKGROUND = "#111111"
PANEL = "#222222"
HEAD = "#444444"
STRIPE = "#181818"
INK = "#eeeeee"
TEXT_SECONDARY = "#aaaaaa"
TEXT_MUTED = "#888888"
BORDER = "#444444"
GRID = "#444444"
ACCENT = "#88cc88"
BRAND = "#55bb55"
BRAND_TINT = "#1d2e1d"
PAPER = BACKGROUND  # old name, kept for callers

# Marks
ACTUAL = "#f4f4f4"
CHARGE = "#99dd55"
DISCHARGE = "#ee9944"
HOLD = "#666666"
HOLD_DIM = "#3a3a3a"
BELIEF = "#33aadd"
PERFECT = "#aaaaaa"
GOOD = "#55bb55"
BAD = "#cc4455"
QUESTION = "#eedd00"

ACTION_COLOUR = {"charge": CHARGE, "discharge": DISCHARGE, "hold": HOLD}
ACTION_BAND = {"charge": "#4f9a2f", "discharge": "#c3661f", "hold": HEAD}  # header strips in the wheel
ACTION_GLYPH = {"charge": "▲", "discharge": "▼", "hold": "—"}
ACTION_LABEL = {"charge": "charge", "discharge": "sell", "hold": "hold"}

LONDON = "Europe/London"
DOMINANT_H, SECONDARY_H, STRIP_H = 300, 180, 56
FONT = "Proza Libre"
MONO = "IBM Plex Mono"

# One-hue sequential ramp for price level (the wheel's inner ring): dark = cheap, light = dear.
_RAMP = ("#1c3542", "#2a7ea6", "#33aadd", "#9fdcf5")


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def ramp(t: float) -> str:
    """Colour at t in [0, 1] along the price ramp."""
    t = 0.0 if pd.isna(t) else min(1.0, max(0.0, float(t)))
    pos = t * (len(_RAMP) - 1)
    i = min(int(pos), len(_RAMP) - 2)
    f = pos - i
    a, b = _hex(_RAMP[i]), _hex(_RAMP[i + 1])
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b, strict=True))


@alt.theme.register("tempo", enable=True)
def tempo_theme() -> alt.theme.ThemeConfig:
    return {
        "config": {
            "background": "transparent",
            "view": {"stroke": None},
            "font": FONT,
            "axis": {
                "domain": False,
                "gridColor": GRID,
                "tickColor": GRID,
                "labelColor": TEXT_SECONDARY,
                "labelFont": FONT,
                "labelFontSize": 12,
                "titleColor": TEXT_SECONDARY,
                "titleFont": FONT,
                "titleFontSize": 12,
                "titleFontWeight": 400,
            },
            "legend": {
                "labelColor": INK,
                "labelFont": FONT,
                "titleColor": TEXT_SECONDARY,
                "orient": "top",
                "symbolType": "stroke",
            },
            "title": {"color": INK, "font": FONT, "fontSize": 15, "fontWeight": 400, "anchor": "start"},
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
    rule = alt.Chart(df).mark_rule(color=INK, opacity=0.6, strokeWidth=1).encode(x="t:T")
    text = (
        alt.Chart(df)
        .mark_text(align="left", dx=4, dy=-4, baseline="bottom", color=TEXT_SECONDARY, font=FONT, fontSize=12)
        .encode(x="t:T", text="label:N", y=alt.value(0))
    )
    return rule + text
