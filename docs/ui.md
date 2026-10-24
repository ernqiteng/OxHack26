# Tempo UI plan

Owner: Ayo. Companion to [ayo.md](ayo.md) (phases) and [description.md](description.md) (demo script).
This is the design spec for `tempo/dashboard/`. It is written so any of us can pick up a screen and build it
without re-deciding anything.

The job of the UI is a 3-minute demo on a projector in front of HRT, Tiger Data and Vultr judges. Every
decision below is in service of five screens that each land one sentence of the pitch, and one click (the
timing audit) that has to look alive.

---

## 1. Inspiration: what we took from YC companies

We looked at YC-backed products in our domain and at YC products known for UI craft. Marketing pages were
text-scraped, so palette details for the energy companies came from write-ups rather than pixels. Full
sources at the end.

| Company (YC) | What they do | What we take |
|---|---|---|
| **Grid Status** (W23) | Live electricity-market dashboards for US ISOs: prices, load, fuel mix, nodal price maps, alerts | The *market-first* layout: one dominant time-series with a strong "now" line, price on the y axis, and a colour gradient for price level. Dense but calm. Our Live tab is a GB version of this with a decision layer on top. |
| **Dartboard Energy** (W25) | AI analyst for grid-scale battery owners: ingests market data, finds missed revenue | "Missed revenue" as the headline number. Our timing audit should lead with the pound figure, not the chart. |
| **Rewbi** (S24) | AI dispatch for grid batteries, charge cheap / sell dear | Same loop as Tempo. Their pitch is a *fleet of live inputs feeding one decision*. We show the decision and its reason as first-class objects (a hold is a row, not an absence). |
| **Condor Energy** (W25) | Energy procurement: forecasts cost per facility, runs simulations for hedging | Simulations shown as side-by-side scenarios with a delta against the base case. That is exactly the five-timeline view. |
| **Enode** (W21) | Device/grid orchestration; home energy diagram with live kW readouts per asset | Live readouts as compact labelled numbers next to a small diagram, not a wall of metrics. Our battery state (SoC, MW, £) gets this treatment. |
| **inBalance** (acq.) | ML electricity price forecasting | Validated that "forecast with uncertainty band" is the expected visual in this market. We show p10–p90, never a bare line. |
| **Linear** (S19) | Issue tracker; the reference for restrained dark UIs | Near-black surfaces, one chromatic accent, translucent-white borders, Inter with tight tracking, status-first lists, `Fig 0.1` editorial captions. Tempo adopts this system wholesale (tokens in section 3). |
| **PostHog** (W20), **Supabase** (S20), **Resend** (W23) | Dev tools with data-heavy dashboards | Event/log timelines with status badges and timestamps. Our audit progress log ("forking… ready… replaying on tempo-worker-3… £-14.20") is a Resend-style event stream. |

Cross-cutting lessons from fintech/trading dashboard references:

- **Tabular numerals in a monospace face** so live prices and £ figures don't jitter as digits change.
- **Green/red carry sign only, never identity**, and always with a sign character (+£14) so colour is not the only cue.
- **One dominant chart per screen.** Secondary charts are small and sit below or beside it.
- **Status before detail.** The first row of every screen answers "what is it doing right now".

---

## 2. Design principles

1. **One sentence per screen.** Each tab exists to land one line of the demo script. The sentence is rendered on screen in large type, generated from real numbers, so the presenter reads it rather than remembers it.
2. **Hero number, then chart, then table.** Judges read the number, glance at the chart, and only an HRT judge will open the table. All three exist; the order is fixed.
3. **Honesty is a surface, not a tab.** The source badge (synthetic / Tiger), the stated assumptions, and the "% of perfect" figure are visible on every screen in the header strip.
4. **Time is the x axis everywhere and "now" is always drawn.** Every time-series chart shares the same x encoding, the same now-rule, and the same settlement-period gridlines, so the eye never re-learns a chart.
5. **Decisions are objects.** Charge, discharge and hold each have a fixed colour and glyph. A hold is rendered with its reason, never as blank space.
6. **Motion only where it carries meaning.** The replay plays forward, the audit log streams, the £ ticks up. Nothing else animates.
7. **Projector-safe.** Dark theme by default (it reads as "trading terminal"), but every colour clears 3:1 on its surface and we ship a light theme that is one click away in case the room's projector washes out blacks.

---

## 3. Visual system

### 3.1 Theme tokens (Streamlit 1.66 `.streamlit/config.toml`)

Everything below is config, not CSS. Custom CSS is a last resort (section 8).

```toml
[theme]
base = "dark"
primaryColor = "#7170ff"            # Linear accent violet; CTAs, active tab, "as decided"
backgroundColor = "#0f1011"         # panel dark
secondaryBackgroundColor = "#191a1b"# cards, widgets, code
textColor = "#f7f8f8"
linkColor = "#828fff"
borderColor = "#23252a"
dataframeBorderColor = "#23252a"
dataframeHeaderBackgroundColor = "#191a1b"
codeBackgroundColor = "#141516"
baseRadius = "8px"
buttonRadius = "6px"
showWidgetBorder = true
showSidebarBorder = false
font = "Inter"
headingFont = "Inter"
codeFont = "JetBrains Mono"
baseFontSize = 15
headingFontSizes = ["2rem", "1.5rem", "1.2rem", "1rem", "0.9rem", "0.8rem"]
headingFontWeights = [590, 590, 510, 510, 510, 510]
chartCategoricalColors = ["#199e70", "#d95926", "#9085e9", "#8a8f98"]
greenColor  = "#0ca30c"
redColor    = "#d03b3b"
orangeColor = "#ec835a"
grayColor   = "#8a8f98"

[[theme.fontFaces]]
family = "Inter"
url = "app/static/Inter-Variable.woff2"   # self-host, venue wifi may block Google Fonts
weight = "100 900"
[[theme.fontFaces]]
family = "JetBrains Mono"
url = "app/static/JetBrainsMono-Variable.woff2"
weight = "100 800"

[theme.light]
primaryColor = "#5e6ad2"
backgroundColor = "#f7f8f8"
secondaryBackgroundColor = "#ffffff"
textColor = "#0b0b0b"
borderColor = "#d0d6e0"
chartCategoricalColors = ["#1baf7a", "#eb6834", "#6250d6", "#62666d"]

[server]
enableStaticServing = true
```

Fonts go in `tempo/dashboard/static/`. If self-hosting slips, fall back to `font = "sans-serif"` (Source Sans)
and `codeFont = "monospace"`; the layout does not depend on the face.

### 3.2 Chart palette (validated)

Run through the dataviz palette validator; all pairs pass CVD and normal-vision separation in both modes.

| Role | Dark | Light | Rule |
|---|---|---|---|
| **charge** | `#199e70` aqua | `#1baf7a` | always paired with glyph `▲` and label "charge" |
| **discharge** | `#d95926` orange | `#eb6834` | glyph `▼`, label "sell" |
| **hold** | `#8a8f98` gray | `#62666d` | glyph `—`, label "hold", reason in tooltip and in the hold card |
| **Tempo's belief** (forecast p50, band, "as decided" timeline) | `#9085e9` violet | `#6250d6` | band is the same hue at 18% opacity; line is 2px |
| **actual price** | `#f7f8f8` text-primary | `#0b0b0b` | 2px line; the truth is always ink-coloured |
| **perfect foresight** | `#d0d6e0` dashed | `#52514e` dashed | dashed means "hindsight" everywhere |
| **good / bad delta** | `#0ca30c` / `#d03b3b` | same | status colours; sign character always present |
| **now rule** | `#f7f8f8` 1px, 60% opacity | same | vertical rule plus "now" label at top |

Do not use blue. Blue and the violet accent fail the separation test; the accent *is* the chart's blue.

Light-mode aqua sits at 2.65:1 on the light surface, so charge bars always carry a direct label or glyph.

### 3.3 Typography scale

| Use | Spec |
|---|---|
| Hero sentence | 28px / 510 / tracking −0.5px, Inter |
| Hero number | 44px / 590, JetBrains Mono, `font-variant-numeric: tabular-nums` |
| Section heading (`st.subheader`) | 19px / 510 |
| KPI value (`st.metric`) | mono, 24px |
| Body | 15px / 400 |
| Caption / source line | 13px / 400, text-tertiary `#8a8f98` |
| Figure label ("Fig 2.1 · five timelines") | 11px / 510 / uppercase / tracking +0.6px, text-quaternary |

### 3.4 Shared chart grammar (Altair)

Register one Altair theme (`tempo/dashboard/theme.py`) and pass `theme=None` to `st.altair_chart` so Streamlit
does not override it:

- Background transparent, no chart border, grid `rgba(255,255,255,0.06)`, axis domain hidden, tick labels in
  text-tertiary at 12px mono.
- x axis is always `:T` in **Europe/London**, with a tick every 6 h and a minor grid every settlement period
  when the window is ≤ 48 h.
- Every time chart gets `now_rule(ts)` layered on top: `mark_rule` + `mark_text(align="left", dy=-6)`.
- Height: dominant chart 320px, secondary charts 180px, strips 56px.
- Tooltips on every mark; `tooltip` always includes the local time, the settlement period number and the value
  in £/MWh or £.

---

## 4. Information architecture

Top navigation via `st.navigation(position="top")`, pages in demo order. Tabs stay as fallback if `st.navigation`
fights `AppTest` in the smoke test.

```
Tempo ⚡   Live   Replay   Timing audit   Honesty   About                    ● Tiger  ● 5/5 workers  ○ synthetic
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
Fri 24 Oct 2026 · SP 31/48 · 15:00–15:30 BST                  Tempo captures 70.1% of perfect foresight (12 wk)
```

**Header strip (every page, `@st.fragment(run_every="30s")`):**

- Left: settlement date, current period, local window. The period number advances live during the demo.
- Right: the single honesty number, always visible. Clicking it jumps to Honesty.
- Far right: three status dots. `● Tiger` (connected), `● 5/5 workers` (from `demo_reset`'s health checks, cached
  60 s), `○ synthetic` lights amber when any query fell back. This replaces the current per-method yellow warning
  boxes, which get collected into one expander at the bottom of the page ("3 fields are synthetic, show which").

---

## 5. Screens

### 5.1 Live — "Here is what the battery is doing right now, and why."

```
┌ SoC ───────┐ ┌ Next action ────────┐ ┌ Today so far ─┐ ┌ Forecast spread ──────┐
│ 1.2 MWh    │ │ ▲ charge 1 MW       │ │ +£38.40       │ │ £41 → £83 /MWh        │
│ ▁▂▃▅▆ 60%  │ │ 01:30 BST, in 10 h  │ │ 2 cycles      │ │ p10–p90 width £22     │
└────────────┘ └─────────────────────┘ └───────────────┘ └───────────────────────┘

Fig 1.1 · APX MID, last 24 h and next 24 h
┌──────────────────────────────────────────────────────────────────────────────────┐
│ £/MWh                              now│                                          │
│ 120 ─           actual (ink)         │        p50 (violet) + p10–p90 band       │
│  80 ─   ╱╲    ╱╲                     │   ╭──────╮            ╭────╮             │
│  40 ─ ╱    ╲╱    ╲____               │╭──╯      ╰────────────╯    ╰──           │
│   0 ─                                │                                          │
│     ▲▲▲▲                    ▼▼▼▼     │ ▲▲▲▲                 ▼▼▼▼               │
│     00:00    06:00    12:00    18:00 │ 00:00    06:00    12:00    18:00         │
└──────────────────────────────────────────────────────────────────────────────────┘

Fig 1.2 · Today's schedule, 48 periods                        charge ▲  sell ▼  hold —
│ 1 ░░▲▲▲▲▲▲░░░░░░░░░░░░░░░░░░░░░░ ▼▼▼▼ ░░░░░░░░ 48 │   ← current period outlined in accent

┌ Latest hold ─────────────────────────────────────────────────────────────────────┐
│ — Held 14:30–15:00.  Expected spread £11.20 did not cover £18.00 in losses       │
│   (10% round trip + £10/MWh degradation).  Decided 14:25 from forecast #8812.    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Details:

- **One continuous chart** for past actual and future forecast, split by the now-rule. The actual line stops at
  now; the band starts at now. This is the single most important chart in the product and it is the only
  thing on the screen above the fold besides the four KPI tiles.
- Action glyphs are drawn as a `mark_point(shape="triangle-up"/"triangle-down")` row along the bottom of the
  chart, so decisions sit on the price they react to.
- The **48-period strip** is an Altair `mark_rect` with one cell per settlement period, coloured by action, with
  the current period outlined in the accent. Hover shows period, time, action, MW, expected spread, reason.
- KPI tiles use `st.metric(border=True)` with `chart_data` sparklines (SoC over 24 h, PnL over today).
- The hold card is a bordered `st.container`, never a `st.warning`: a hold is a correct decision, not a problem.

### 5.2 Replay — "Play a windy week forward and watch the £ tick up."

```
Week of 5 Jan 2026 · windy regime ▾            ▶ Play   ⏸   ⏮      speed  1×  4×  16×
Fig 2.1 · Forecast band vs actual, battery actions
┌──────────────────────────────────────────────────────────────────────────────────┐
│ (same grammar as Fig 1.1; the playhead is the now-rule and moves)               │
└──────────────────────────────────────────────────────────────────────────────────┘
┌ State of charge ───────────────────┐ ┌ Cumulative £ ──────────────────────────────┐
│ area, 0–2 MWh                      │ │ step line, Tempo solid; perfect dashed     │
└────────────────────────────────────┘ └────────────────────────────────────────────┘
                                   £ 612.40  so far   ·   61% of perfect this week
──────────────────────────── scrubber (periods 1–336) ────────────────────────────
```

Details:

- Playback is `@st.fragment(run_every=0.4)` incrementing `st.session_state.replay_idx` while
  `replay_playing` is true. The fragment re-renders only the charts and the hero number, not the page.
- The hero number is mono and tabular so it ticks without shifting layout.
- Perfect-foresight £ is drawn dashed on the same chart so the gap is visible as it opens and closes.
- Week picker lists windy and calm weeks from `backtest_results.regime`, so the presenter can show a calm week
  where Tempo holds a lot and still beats the simple rule.

### 5.3 Timing audit — "Click a decision. Five timelines. An hour later would have cost £31."

The signature screen. It must look alive for 40 seconds and then land one sentence.

```
Decision   #8812 · Wed 22 Oct 01:30 · ▲ charge 1 MW ▾           Mode  ● Tiger forks   ○ in-process
                                                                   [ Run timing audit ]

Fig 3.1 · Five timelines                                                     elapsed 00:47
┌ −1 h ────┐ ┌ −30 min ─┐ ┏ as decided ━━━━━┓ ┌ +30 min ─┐ ┌ +1 h ───────┐
│ £106.20  │ │ £118.90  │ ┃ £124.10         ┃ │ £109.80  │ │ £93.40      │
│ −£17.90  │ │ −£5.20   │ ┃ ●               ┃ │ −£14.30  │ │ −£30.70     │
│ ✓ worker-1│ │ ✓ worker-2│ ┃ ✓ worker-3      ┃ │ ◌ replaying│ │ ◌ queued    │
│ ▁▃▅▆▇▆▅  │ │ ▁▃▅▇▇▆▅  │ ┃ ▁▂▅▇█▇▅         ┃ │ ▁▁▃▅▇▇▆  │ │ ▁▁▂▃▅▇▇     │
└──────────┘ └──────────┘ ┗━━━━━━━━━━━━━━━━━┛ └──────────┘ └─────────────┘

   Charging one hour later would have cost £30.70.  Tempo picked the best of the five.

Fig 3.2 · Cost of mistiming (£ vs as decided)
   −1 h   ████████████ −17.90
 −30 min  ████ −5.20
  as decided  │ 0
 +30 min  ██████████ −14.30
   +1 h   █████████████████████ −30.70

┌ Audit log ───────────────────────────────────────────────────────────────────────┐
│ 00:00.0  fork audit-8812-all requested (Tiger, fork_strategy NOW)                │
│ 00:36.3  audit-8812-all READY, 5 timelines dispatched                            │
│ 00:36.4  audit-8812-0 dispatched to tempo-worker-3 (ewr)                         │
│ 00:37.6  tempo-worker-3 → £124.10                                                 │
│ …                                                                                 │
│ 00:38.0  5/5 done, fork deleted                                                   │
└──────────────────────────────────────────────────────────────────────────────────┘

Self-grade · timing within one period of hindsight-optimal on 71% of 38 cycles · mean cost of mistiming £9.40
```

Details:

- **Choreography.** On click, `run_audit(mode="fork")` runs in a background thread writing per-shift state
  to a dict in `st.session_state`. A `@st.fragment(run_every=0.5)` re-renders only Fig 3.1 and the log. Each
  column goes through states `queued → forking → ready → replaying on worker-N → £` with `st.status`-style
  icons. A failed shift shows `✗ failed` in status red and the other four still render.
- The five columns are `st.columns(5, border=True)`; the middle one gets the accent border (the one place
  custom CSS is allowed, keyed `st-key-audit-col-0`).
- Each column carries a 48-period SoC sparkline so the shift is *visible*: the hump moves right as the shift
  increases.
- The **hero sentence** is generated: pick the worst of the ±1 and ±2 shifts, phrase it with the action verb,
  and add the second clause only if shift 0 is the maximum ("Tempo picked the best of the five"). If a
  shifted timeline beats shift 0, say so plainly ("Charging 30 minutes earlier would have earned £5 more").
  Honesty is the brand.
- Fig 3.2 is a diverging bar of `pnl_delta_gbp` around zero, good green right, bad red left, labelled with the
  signed value. One axis, no legend needed.
- The mode toggle is `st.segmented_control`. In-process is the on-stage fallback ("same replay, run locally").
- The log is a `st.container(height=180)` of monospace lines with elapsed stamps. It is the Vultr and Tiger
  story told in their own vocabulary (fork names, worker ids, regions).

### 5.4 Honesty — "Here is what we captured, against honest baselines, on weeks the model never saw."

```
                       70.1%
      of perfect-foresight profit captured over 12 unseen weeks

Fig 4.1 · Walk-forward backtest
  Perfect foresight          ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  £4,120  100%
  Tempo (LightGBM + LP)      ████████████████████████████████████            £2,890   70%
  Persistence + same LP      ████████████████████████████                    £2,410   58%
  Simple rule 01–05 / 17–19  ██████████████████████                          £1,980   48%

┌ Calibration ──────────────────────┐ ┌ By regime ───────────────────────────────┐
│ observed vs nominal, 45° dashed   │ │ calm │ windy  — grouped bars, same order │
│ band held 86% vs 80% target       │ │ as Fig 4.1, Tempo in accent              │
└───────────────────────────────────┘ └──────────────────────────────────────────┘

Where it's weak
 · On calm summer weeks the simple rule captures nearly as much as Tempo.
 · The p10–p90 band held 86% of prices against an 80% target: slightly under-confident.
 · MID prices carry no publish time; availability is stated as period end + 10 min.
 · We assume the battery transacts at the APX within-day index; a real unit would trade day-ahead.

Storage · 9,800,000 rows in grid_raw · compressed 90% (10.0×) · 2-year query 0.21 s
```

Details:

- Hero number first, 44px mono. The percentage is the product's honest scorecard.
- Fig 4.1 is a horizontal bar ladder, not a table. Tempo's bar is in accent, others gray, perfect is a dashed
  rule at 100%. Colour follows the entity, so Tempo is violet on every screen.
- The table from `backtest_summary` still exists, inside an expander below the chart for the HRT judge.
- "Where it's weak" is plain sentences in body type, no icons, no warning boxes. It reads as confidence.
- Storage line is where Tiger compression gets its credit; add query timing if Girik exposes it.

### 5.5 About — the architecture on one screen

A single diagram (inline SVG or a static PNG) of the data flow from description.md section 4, with the Tiger
and Vultr boxes in their brand colours, plus the stated assumptions and the team. No charts. This is the tab
left open during Q&A.

---

## 6. Components to build (`tempo/dashboard/ui.py`)

Small helpers so every screen is assembled from the same pieces:

| Helper | Renders |
|---|---|
| `header_strip(src)` | the fragment in section 4 |
| `hero(sentence, number=None)` | big sentence / number block |
| `kpi(label, value, delta=None, spark=None)` | `st.metric(border=True)` with formatting rules (£ with 2 dp, MWh with 1 dp, % with 1 dp) |
| `fig_label(n, title)` | the `Fig 1.1 · title` caption line |
| `price_chart(df, now, actions=None)` | Fig 1.1 / 2.1 with band, now-rule, action glyphs |
| `period_strip(sched, current)` | Fig 1.2 |
| `timeline_card(shift, state, pnl, delta, soc_path, highlight)` | one audit column |
| `delta_bars(rows)` | Fig 3.2 |
| `ladder(summary)` | Fig 4.1 |
| `decision_card(hold)` | the hold card |
| `status_dot(label, ok)` | header dots |

`theme.py` holds the Altair theme, the colour constants (`CHARGE`, `DISCHARGE`, `HOLD`, `BELIEF`, `INK`,
`GOOD`, `BAD`) and `pick_theme()` reading `st.context.theme.base` to swap light/dark constants.

---

## 7. Build order

Ordered by demo payoff per hour. Each step leaves the app runnable and the smoke test green.

| # | Step | Est. | Lands |
|---|---|---|---|
| 1 | `config.toml` theme + fonts in `static/`, `theme.py` with Altair theme and colour constants | 45 min | The whole app changes character in one commit |
| 2 | `ui.py` helpers: `kpi`, `hero`, `fig_label`, `header_strip`, status dots; collapse the yellow notes into one expander | 1 h | Every screen gets the header and the same tiles |
| 3 | Live: continuous past+future chart with now-rule and action glyphs; 48-period strip; hold card | 1.5 h | Screen 1 of the demo |
| 4 | Timing audit: five bordered columns with states, hero sentence, delta bars, log container; wire to in-process | 2 h | Screen 3 in fallback mode |
| 5 | Timing audit: background thread + fragment polling for fork mode; per-shift state machine | 1.5 h | Screen 3 live (needs Phase 2 orchestrator) |
| 6 | Honesty: hero %, ladder chart, calibration, regime, weak points, storage line | 1 h | Screen 4 |
| 7 | Replay: play/pause fragment, scrubber, perfect-foresight dashed line, ticking £ | 1.5 h | Screen 2 |
| 8 | About diagram; light theme check on the venue projector; record backup | 45 min | Q&A and safety |

Steps 1–4 and 6 are must-have. 5 depends on Phase 2. 7 and 8 cut first.

---

## 8. Rules

- **No custom CSS** except the accent border on the "as decided" column. Everything else is config.toml or a
  Streamlit primitive. CSS breaks across Streamlit versions and we are on 1.66.
- **No dual-axis charts.** Price and SoC never share a plot; they stack.
- **No pie charts, no gauges, no rainbow colour scales.**
- **No `st.warning` for a hold** and no `st.error` for a planned fallback. Problems use the status dots; the
  warning colour is reserved for a shift that actually failed.
- **Every number has a unit** and £ has two decimals on screen, zero in the backtest ladder.
- **Every time is Europe/London** on screen, UTC in the database. The axis says "BST" or "GMT".
- **Legends only when ≥ 2 series**, and glyph + label for actions so colour is never the only cue.
- **Nothing auto-refreshes faster than it changes.** Header strip every 30 s, audit fragment every 0.5 s only
  while an audit is running, replay fragment only while playing.

---

## 9. Sources

- YC energy directory: https://www.ycombinator.com/companies/industry/energy
- Dartboard Energy: https://www.ycombinator.com/companies/dartboard-energy
- Rewbi: https://www.ycombinator.com/companies/rewbi
- Condor Energy: https://www.ycombinator.com/companies/condor-energy
- NODI Energy: https://www.ycombinator.com/companies/nodi-energy
- Enode: https://enode.com
- Grid Status product description: https://www.preqin.com/data/profile/asset/grid-status-inc-/700360 and
  https://www.canarymedia.com/articles/clean-energy/grid-status-lands-8m-to-expand-its-open-source-mapping-of-the-us-grid
- Linear design tokens (third-party write-up): https://cdn.jsdelivr.net/npm/oh-my-opencode@4.18.2/dist/skills/frontend/references/design/linear.app.md
- Fintech dark dashboard conventions (tabular numerals, sign + colour): https://cdn.jsdelivr.net/npm/@wrongstack/core@0.295.1/design-kits/fintech-dark/KIT.md
- Streamlit theming options: https://docs.streamlit.io/develop/concepts/configuration/theming-customize-fonts and
  https://skills.cat/skills/streamlit/agent-skills/creating-streamlit-themes
- Streamlit 2025–26 release notes (top navigation, `st.context.theme`, fragments): https://docs.streamlit.io/develop/quick-reference/release-notes/2025
