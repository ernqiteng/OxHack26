# Tempo UI plan: two pages in the Toven style

> **Dashboard theme superseded (25 Oct).** The dashboard (`tempo/dashboard/`) now follows
> [grid.iamkate.com](https://grid.iamkate.com/) (National Grid: Live, CC0) rather than the paper theme in
> section 5: page `#111`, `#222` panels with `#444` header strips, Proza Libre throughout, green links, and a
> central **plan wheel**: today's 48 settlement periods on a 24-hour clock (outer ring = charge / sell / hold
> per period, inner ring = forecast p50 on a one-hue ramp, current period outlined), with the plan's blocks
> tabled on the left (Charge / Sell / Hold bands) and the market and battery on the right. Above it sit two
> KPI panels (Time · Period · Price · Next action, and Captured = Tempo ÷ Perfect) and a tab-style section
> nav; below it one panel per demo section, each opened by its generated sentence. Tokens live in
> `tempo/dashboard/theme.py` and `.streamlit/config.toml`; the page stylesheet and the wheel are in
> `tempo/dashboard/ui.py` (the wheel is rendered through `st.markdown`, because `st.html` strips inline SVG).
> Screenshots: `docs/screenshots/grid_top.png`, `grid_full.png`, `grid_audit.png`. Section 4's screen
> content and chart grammar still apply; the pitch page plan below is unchanged.

Owner: Ayo. Supersedes the visual system in [ui.md](ui.md) (that file's screen content and chart rules still
apply; its dark Linear theme does not). Demo script in [description.md](description.md) section 6.

Two pages, one theme:

1. **Pitch page** (`/`): a re-creation of toven.ai's style, layout and animations with Tempo's content.
2. **Dashboard** (`/app`): the five demo screens, in the same theme.

A full mirror of toven.ai (HTML, CSS, JS bundles, fonts, assets), 20 rendered screenshots at desktop and
mobile widths, and the Playwright script that took them are in `reference/toven/` (gitignored, so copy it
from Ayo's machine if you need it). Everything in section 2 was extracted from that mirror, not guessed.

**Rule on reuse.** We copy the *system*: tokens, type, layout, components, motion. We do not ship any Toven
asset, name,◊ logo, partner logo or sentence. Every image, icon and word on our page is ours.

---

## 1. Stack

Toven is Next.js (App Router, Turbopack), Tailwind v4 (`@theme` CSS variables), Framer Motion
(`motion/react`), lucide-react icons, and `next/font` for Libre Baskerville, IBM Plex Sans and IBM Plex Mono.
Illustrations are hand-written inline SVG with CSS keyframes in a `<style>` tag next to each one.

We use the same stack for the pitch page so the clone is one-to-one:

```
web/                      Next.js 15 app, static export
  app/page.tsx            the pitch page
  app/globals.css         @theme tokens (section 2.1)
  components/             Reveal, Eyebrow, Nav, Hero, StatPills, Hub, Slides, Steps, Honesty, CTA, Footer
  components/illos/       inline SVG illustrations with their keyframes
  public/                 our own logo mark and sponsor marks
```

Dashboard: two options. Pick A now, move to B only if steps 1 to 6 of [ui.md](ui.md) section 7 are green.

| | A: Streamlit, re-themed | B: React in the same Next app |
|---|---|---|
| Theme match | Close. Fonts, colours, radii and borders all map to `config.toml` (section 5.1). Serif headings work. Card chrome is Streamlit's, not Toven's. | Exact. Same components as the pitch page. |
| Cost | ~1 h to re-theme what exists; charts and tests already there | 1.5 to 2 days: FastAPI JSON layer on `DbSource`, charts in Recharts or visx, audit progress over SSE |
| Serving | nginx on the backend box: `/` → static export, `/app` → `127.0.0.1:8501` with websocket upgrade | one Next server |
| Risk | Streamlit reruns during the fork audit; mitigated with fragments (ui.md 5.3) | new code on the night |

Either way the pitch page's primary button links to `/app`, and the dashboard's nav links back to `/`.

---

## 2. The Toven system, extracted

### 2.1 Tokens (from `:root` in the shipped CSS)

```css
@theme {
  --background:          #fafaf8;   /* warm paper, every page */
  --foreground:          #1c1917;
  --surface:             #ffffff;   /* cards */
  --surface-elevated:    #f5f5f0;   /* alternating section bands */
  --surface-sunken:      #f0f0ea;
  --border:              #d6d3d1;
  --border-light:        #e7e5e4;
  --text-primary:        #1c1917;
  --text-secondary:      #78716c;
  --accent-primary:      #44403c;   /* icons, eyebrow text, hover borders */
  --accent-primary-hover:#292524;
  --brand:               #1a4d3e;   /* deep green: buttons, dots, logo square */
  --brand-dark:          #0f2e25;   /* button hover */
  --brand-tint:          #e9f0ed;   /* stat pills, highlighted nodes */
  --status-approve:      #15803d;
  --status-reject:       #991b1b;
  --status-questions:    #92400e;
  --status-uncertain:    #1e40af;
  --radius-md: .375rem;  --radius-lg: .5rem;  --radius-xl: .75rem;
  --ease-out: cubic-bezier(0,0,.2,1);  --ease-in-out: cubic-bezier(.4,0,.2,1);
  --default-transition-duration: .15s;
}
```

Tempo additions for chart marks (section 5.2 validates them): `--charge #1f8a5a` (a lighter step of the
brand green; the brand green itself is too dark and too grey for a line), `--discharge #c2410c` (burnt
orange), `--hold #a8a29e` (stone), `--belief #2563eb` (a lighter step of Toven's "uncertain" blue, for the
forecast band), `--perfect #78716c` dashed.

### 2.2 Type

| Role | Face | Size / weight / tracking |
|---|---|---|
| `html` default and all headings | **Libre Baskerville** 400/700 | h1 `2.5rem → 3.75rem (sm) → 4.5rem (lg)`, 700, `leading-[1.05] tracking-tight`; h2 `1.875rem → 2.25rem`, 700; h3 (slides) `1.5rem`, 700 |
| Body, buttons, nav, card titles | **IBM Plex Sans** 400/500/600/700 | body `1rem`, lead paragraph `1.125rem leading-relaxed text-text-secondary max-w-xl`; nav links `0.875rem 600 uppercase tracking-[0.1em]` |
| Eyebrows, labels, chart text | **IBM Plex Mono** 400/500/700 | `0.75rem uppercase tracking-[0.2em]`, `text-text-secondary` (or `text-accent-primary` in the hero) |

Serif body is the signature: paragraphs inside cards and slides switch to `font-sans`, everything else inherits
the serif.

### 2.3 Layout

- Nav: `fixed top-0 h-16`, `max-w-7xl mx-auto px-6`, logo square 40×40 `bg-brand rounded-lg` left, four
  uppercase links centred, "Log in" text link + primary button right. Below 768px: hamburger.
- Content width: `max-w-6xl` for sections, `max-w-5xl` for the hero text block, `max-w-7xl` for nav/footer.
- Section rhythm: `py-16` (stats), `py-24` (features), `min-h-screen` (hero, final CTA). Bands alternate
  `bg-background` / `bg-surface-elevated` down the page: hero paper → band → paper (slides) → band (steps) →
  paper (security) → band (CTA) → footer with `border-t`.
- Two-column feature rows: `grid lg:grid-cols-2 gap-12 items-center`, illustration card and copy swap sides
  each row (`order-1 lg:order-2`).
- Card: `bg-surface border border-border rounded-xl shadow-sm overflow-hidden`; illustration cards are
  680×380 SVG viewBoxes with a white `rx=16` rect.
- Stat pills: `bg-brand-tint border border-brand/20 rounded-xl px-6 py-3`, value `font-bold text-brand`.
- Feature tiles (6-up): `rounded-xl p-5 sm:p-8 flex-col items-center text-center`, lucide icon 24px
  `text-accent-primary`, title `text-base font-sans font-semibold`, `hover:border-accent-primary
  transition-colors duration-300`. The seventh tile is `border-dashed` and `text-text-secondary/50`.
- Buttons: primary `bg-brand text-white font-sans font-semibold rounded-lg text-sm px-6 py-2.5
  hover:bg-brand-dark transition-colors`; large variant `text-base px-8 py-3`. Secondary: `border
  border-border rounded-lg px-4 py-2 hover:bg-surface-elevated`.

### 2.4 Motion (every value from the bundle)

**Reveal** (the one component used ~40 times):

```tsx
const variants = { hidden: { opacity: 0, y: 24 }, visible: { opacity: 1, y: 0 } };
<motion.div variants={variants} initial="hidden" whileInView="visible"
  viewport={{ once: true, margin: "-80px" }}
  transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1], delay }} />
```

Hero stagger: `delay = 0.08 * (i + 2)` per block (h1 0.16, lead 0.24, button 0.32, eyebrow 0.40, pills
0.48, logos 0.56). Everywhere else `delay` is 0 or `0.08 * index` across a grid.

**Nav**: `scrollY > 20` toggles `bg-background/80 backdrop-blur-md border-b border-border`, `transition-all
duration-300`. Logo click smooth-scrolls to top.

**Hero background**: one absolutely positioned SVG, `viewBox 0 0 1440 800`, `preserveAspectRatio
xMidYMid slice`, `text-brand opacity-50`, masked with `radial-gradient(ellipse 60% 55% at 50% 45%,
rgb(0 0 0 / 0.6) 0%, black 80%)` so it fades toward the centre behind the headline. Contents: 4 horizontal
and 5 vertical lines (`stroke-width .5`, opacity .24 to .40), 8 right-angle "circuit" paths
(`stroke-width .8`), 4 diagonals, ~28 node circles (r 1.5 to 3, opacity .32 to .6), and 3 to 5 pulse
circles (`r 4–5`, fill `radialGradient` brand → transparent) that travel along the lines with
`<animateMotion dur="7s|11s|13s" repeatCount="indefinite" begin="0|1.5s|3s">`. Pointer-events none.

**Solutions scrollytelling**: outer `section` with `style="height: 700vh"` (one viewport per slide, 7
slides); inner `div.sticky.top-0.h-screen.overflow-hidden`. Slide index = `floor(scrollProgress * 7)`.
Slides swap through `AnimatePresence mode="wait"` with direction-aware variants:

```ts
enter:  (dir) => ({ opacity: 0, y: dir > 0 ? 40 : -40 }),
center:          { opacity: 1, y: 0 },
exit:   (dir) => ({ opacity: 0, y: dir > 0 ? -40 : 40 }),
transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] }
```

Right-hand dot rail (`fixed right-8`, vertical): one 16px dot per slide, active dot `scale(1.25)` with
`box-shadow 0 0 0 4px color-mix(in srgb, var(--brand) 15%, transparent)`, `transition transform 300ms,
box-shadow 300ms`; the dot fills top-down (`height: progress%`, `transition height 80ms linear`) as you
scroll through its slide, with 2×16px connectors that fill the same way. Dots are buttons that jump to the
slide. Slide 0 is the overview grid, slides 1 to 5 are one feature each, slide 6 is "what's next".

**Illustrations** (inline SVG + scoped keyframes, `useReducedMotion` turns the loops off):

| Name | Keyframes | Timing |
|---|---|---|
| cycle | opacity 0 → 1 at 4–5% → hold → 0 at 90–97% | `6400ms` or `7000ms ease-in-out infinite`, restarts via a React counter on `setInterval` so the pop-ins replay |
| popIn | `scale(.85)` opacity 0 → 1 | `0.4–0.42s`, overshoot `cubic-bezier(.34,1.56,.64,1)`, staggered `+0.09s` to `+0.15s` per node |
| flow | `stroke-dasharray 6 4`, `stroke-dashoffset 60 → 0` | `1.8–2.8s linear infinite`, one speed per edge |
| ping | `scale(1) .6 → scale(2) 0` | `2.4s ease-out infinite`, `transform-origin` on the hub |
| checkDraw | `stroke-dashoffset 28 → 0` | per tick, `both` |
| rise | `translateY(6px)` 0 → 1 | `0.35s ease-out`, delays `.5 .75 1.0 1.25s` |
| drawLine | `stroke-dashoffset 900 → 0` | the step-03 chart line, then `fill` fades in `0.8s` at `1.4s`, annotations rise at `1.8s` and `2.1s` |
| hub spokes | nodes pop in around a circle (`cos/sin` placement, radius ~150) at `+0.09s` steps, then centre pops at `0.9s` | |

Everything else is `transition-colors` at 150 to 300ms. No scroll-jacking, no parallax, no Lottie, no canvas.

---

## 3. Page 1: the pitch page

Section-by-section mapping. Left column is Toven's section, right is ours. Layout, classes and motion are
identical; only content and illustrations change.

### 3.0 Nav

Logo: 40×40 `bg-brand rounded-lg` square with a white glyph. Ours is a half-filled circle (a clock at
half past), not a letter. Links: `HOW IT WORKS · TIMING AUDIT · HONESTY · STACK`. Right: `GitHub` text link,
primary button **Open the dashboard** → `/app`.

### 3.1 Hero (`min-h-screen`, paper, circuit-grid SVG)

Our grid SVG keeps the geometry but the vertical lines sit at 48 equal steps across a 24-hour band
(every 30 px = one settlement period, every 6th line darker), so the backdrop *is* the settlement-period
grid. Pulses travel left to right along the horizontal lines.

```
                 A battery that knows when.
   Electricity in Britain is priced every half hour: cheap at 3am when it's windy,
   expensive at 6pm when everyone gets home. Tempo forecasts those prices, decides
   when a battery should charge, sell or deliberately do nothing, then proves each
   decision was made at the right moment.
                      [ Open the dashboard ]

          THE MARKET TEMPO TRADES IN                       ← mono eyebrow, accent
   [48 periods a day] [2 MWh / 1 MW battery] [2 years of GB prices] [5 parallel timelines]

   BUILT ON                                   BUILT AT
   Tiger Data · Vultr · Elexon BMRS           OxHack 2026 · HRT track
```

Pills use the stat-pill component; the two logo rows use our sponsor marks (Tiger, Vultr, Elexon as
wordmarks in `mix-blend-multiply`), and plain text for OxHack and HRT.

### 3.2 Band: "Data" (Toven's Deployment hub, `py-16 bg-surface-elevated`)

Left: hub illustration card. Centre node **TEMPO · decision engine** in brand green, 8 spokes with
`flow`-animated dashed edges: APX MID price, Wind forecast, National demand, Generation mix, Tiger
hypertables, Continuous aggregates, Compression, Availability stamp. Caption line: "Every row carries the
time it became known. Nothing from the future reaches a decision."

Right: eyebrow `DATA`, h2 **Every row stamped with the moment it became known.**, bold lead
"Two years of GB half-hourly prices, wind, demand and fuel mix, live every 30 minutes.", paragraph on
availability-time stamping and the stated MID delay.

### 3.3 Slides: "What Tempo does" (`height: 700vh`, sticky, 7 slides)

| # | Toven slide | Our slide (eyebrow / h3) | Illustration card |
|---|---|---|---|
| 0 | Overview grid of 6 tiles | `WHAT TEMPO DOES` / **Prediction is the easy part. Timing is the product.** Tiles: Forecast, Decide, Hold, Timing audit, Honesty, *More coming* (dashed) | tiles are lucide: `trending-up`, `scale`, `pause`, `git-fork`, `shield-check`, `ellipsis` |
| 1 | Trade reconstruction | `FORECAST` / **48 half-hours ahead, with its doubt attached.** bullets: persistence baseline, LightGBM, p10/p50/p90 | price curve with a band that widens with horizon (`drawLine` then `fill` fade) |
| 2 | eComms surveillance | `DECIDE` / **Charge, sell, or deliberately do nothing.** bullets: cost gate (10% loss + degradation), greedy then LP, holds logged with a reason | three inputs (forecast, SoC, costs) → hub → `charge / sell / hold` outputs, `flow` edges |
| 3 | Horizon scanning | `TIMING AUDIT` / **Run the same decision an hour earlier and an hour later.** bullets: five Tiger forks, Vultr workers, £ delta, forks deleted after | five vertical timeline columns popping in with `popIn`, middle one brand-filled, `ping` on it |
| 4 | Trade monitoring | `SELF-GRADE` / **Within one period of hindsight on 71% of cycles.** (placeholder: use the number from the DB at build time; on 25 Oct it was 87.5% of 8 cycles) | signal lines converging on a triangle like Toven's alert, recoloured: late/early shifts fade, centre holds |
| 5 | Publication review | `HONESTY` / **Pounds on weeks the model never saw, against baselines that can't cheat.** | document mock becomes the backtest ladder: four bars, perfect dashed at 100% |
| 6 | What's next | `WHAT'S NEXT` / **Battery-size sweeps, similar-day search, a real day-ahead desk.** | four locked tiles + dots, same as Toven |

Each slide is the two-column row (`grid lg:grid-cols-2 gap-12 items-center`), copy with mono eyebrow, serif
h3, sans paragraph, bullet list with 6px dots. Illustration side alternates left/right per slide.

### 3.4 Band: "How it works" (`py-24 bg-surface-elevated`, three steps, `space-y-20`)

Eyebrow `HOW IT WORKS`, h2 **A decision, then a receipt for its timing.**

| Step | Toven | Ours | Illustration |
|---|---|---|---|
| 01 | reads your stack | **Tempo reads the market as it becomes known** | left: `YOUR DATA` column (APX MID, wind, demand, mix); centre hub; right: `TEMPO OUTPUTS` (Forecast ✓, Decision ✓, Hold reason ✓) with `checkDraw` ticks |
| 02 | agents do the first pass | **The optimiser commits only when the edge covers the costs** | Toven's shield becomes a battery outline; four check chips around it: `SoC 0–2 MWh`, `±1 MW rate`, `90% round trip`, `£/cycle degradation`; caption "Every constraint cited, every hold explained." |
| 03 | analysts judge | **Five timelines settle whether the moment was right** | Toven's "compliance work vs headcount" chart becomes **cumulative £: Tempo vs perfect foresight** over 12 unseen weeks, `drawLine` on both, `PROJECTED` label becomes `UNSEEN WEEKS`; caption "The gap is the cost of not knowing the future. The audit prices the cost of mistiming." |

### 3.5 Paper: "Honest by construction" (Toven's Security grid, `py-24`)

Left: eyebrow `HONESTY`, h2 **Honest by construction**, paragraph. Right: 2×3 tiles with lucide icons:

- **No lookahead** · availability-time on every row
- **Unseen weeks only** · walk-forward, never random splits
- **Honest baselines** · simple rule and persistence share the optimiser
- **% of perfect foresight** · the headline metric
- **Calibration shown** · does p10–p90 hold 80%?
- **Weak spots stated** · on screen, not in a footnote

### 3.6 Band: final CTA (`min-h-screen`, centred card `max-w-3xl`)

h2 **See a decision audited, live.** Primary large button **Open the dashboard**. Below the card, small
mono line: `OxHack 2026 · theme TIME · HRT track · built on Tiger Data and Vultr`.

### 3.7 Footer

`border-t border-border`, logo square + wordmark **Tempo**, links `How it works · Timing audit · Honesty ·
Stack · GitHub`, right-aligned team names.

---

## 4. Page 2: the dashboard layout

Screen content, charts and the audit choreography are already specified in [ui.md](ui.md) sections 5 and 6.
What that file did not settle is the *frame* the screens sit in, now that the theme is Toven's paper and
serif rather than a dark terminal. Three candidates, recommendation first.

### 4.1 Recommended: "Report" frame

The dashboard is a long document in the pitch page's own language, with Toven's dot rail as the navigation.

```
┌ nav (identical to the pitch page; "Open the dashboard" becomes "● Tiger · 5/5 workers")  ┐
│                                                                                          │
│  LIVE                                        ← mono eyebrow                   ● ────┐   │
│  Friday 24 October, period 31 of 48          ← serif h2, real numbers         ○     │   │
│  ┌ card ───────────────────────────────────────────────────────────────────┐  ○  dot    │
│  │ past 24 h actual + next 24 h p10–p90 band, now rule, action glyphs      │  ○  rail   │
│  └─────────────────────────────────────────────────────────────────────────┘  ○     │   │
│  [SoC 1.2 MWh] [▲ charge 01:30] [+£38.40 today] [spread £41 → £83]  ← stat pills   │   │
│  ┌ card: 48-period strip ┐  ┌ card: latest hold, serif quote, mono reason ┐         │   │
│                                                                                          │
│  ── band (surface-elevated) ─────────────────────────────────────────────────────────   │
│  REPLAY                                                                                  │
│  A windy week, played forward.                                                          │
│  ┌ card: chart with moving playhead ┐ ┌ card: SoC ┐ ┌ card: cumulative £ ┐  ▶ ⏸ 1× 4×   │
│                                                                                          │
│  ── paper ───────────────────────────────────────────────────────────────────────────   │
│  TIMING AUDIT                                                                            │
│  Charging one hour later would have cost £30.70.      ← serif h2, generated             │
│  ┌ −1 h ┐ ┌ −30 ┐ ┏ as decided ┓ ┌ +30 ┐ ┌ +1 h ┐   five cards, middle brand-bordered   │
│  ┌ card: delta bars ┐ ┌ card: audit log, mono, streaming ┐                              │
│                                                                                          │
│  ── band ────────────────────────────────────────────────────────────────────────────   │
│  HONESTY                                                                                 │
│  70.1% of perfect foresight, over 12 unseen weeks.                                       │
│  ┌ card: backtest ladder ┐ ┌ card: calibration ┐ ┌ card: by regime ┐  2×3 tiles: weak spots │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Why this one: the presenter scrolls through the demo in script order, the judges see the same visual
language as the pitch, the dot rail shows where we are, and every section's h2 is the sentence from the
script, generated from live numbers. Sections alternate paper and band exactly like the pitch page.

In Streamlit (option A) this is one page with `st.navigation(position="top")` holding a single "Dashboard"
page plus anchors; the dot rail is dropped and the top nav links scroll to section anchors. In React
(option B) it is the pitch page's `Slides` rail without the sticky trap: the rail tracks `IntersectionObserver`
on the four sections.

### 4.2 Alternative: "Slides" frame

Reuse the 700vh sticky scrollytelling verbatim: four slides (Live, Replay, Audit, Honesty), one viewport
each, direction-aware swap, dot rail. Strongest on stage, because nothing scrolls partially and every slide
is composed for a 16:9 projector. Weakest for Q&A, where judges want to scroll freely. Only possible with
option B.

### 4.3 Alternative: "Console" frame

Left sidebar (Toven tile style, 56px icons) with the four screens, content area as a card grid. Most
conventional, least like the pitch page, and Streamlit's sidebar makes it nearly free. Fallback if the
Report frame runs long.

### 4.4 Dashboard component rules

- **Eyebrow + serif h2 + sans body** at the top of every section, same `Eyebrow` and heading classes as the
  pitch page. The h2 is always a real sentence with a real number.
- **Cards** are Toven's illustration cards: white, `border-border`, `rounded-xl`, `shadow-sm`, 24px
  padding, chart inside with 16px inset. No card inside a card.
- **Stat pills**, not metric tiles, for the KPI row: `brand-tint` background, value in `font-bold text-brand`,
  unit in sans. SoC pill carries a tiny inline SVG bar.
- **Audit columns** are feature tiles; the as-decided column swaps `border-border` for `border-brand` and
  gets the `ping` ring while the audit runs. States use the `popIn` entrance and lucide `loader-circle`
  (spin) → `check` (`checkDraw`) → value.
- **Audit log** is a `font-mono text-xs` block on `surface-sunken`, lines `rise` in as they arrive.
- **Hold card** is a serif pull-quote: the reason in Libre Baskerville italic, the numbers in mono below.
- **Charts** keep ui.md's grammar (one axis, now rule, glyphs, band at 18%) with the colours in 5.2. Grid
  lines `border-light`, axis text `text-secondary` in Plex Mono 11px.
- **Status** uses Toven's four status colours only: approve for a good delta or a healthy worker, reject
  for a failed shift, questions for a synthetic fallback, uncertain for the forecast band.

---

## 5. Theme mapping

### 5.1 Streamlit `config.toml` (option A)

```toml
[theme]
base = "light"
primaryColor = "#1a4d3e"
backgroundColor = "#fafaf8"
secondaryBackgroundColor = "#f5f5f0"
textColor = "#1c1917"
linkColor = "#1a4d3e"
borderColor = "#d6d3d1"
dataframeBorderColor = "#e7e5e4"
dataframeHeaderBackgroundColor = "#f5f5f0"
codeBackgroundColor = "#f0f0ea"
baseRadius = "0.75rem"
buttonRadius = "0.5rem"
showWidgetBorder = true
showSidebarBorder = true
font = "IBM Plex Sans"
headingFont = "Libre Baskerville"
codeFont = "IBM Plex Mono"
baseFontSize = 16
headingFontSizes = ["2.25rem", "1.875rem", "1.5rem", "1.125rem", "1rem", "0.875rem"]
headingFontWeights = [700, 700, 700, 600, 600, 600]
chartCategoricalColors = ["#1f8a5a", "#c2410c", "#2563eb", "#a8a29e"]
greenColor  = "#15803d"
redColor    = "#991b1b"
orangeColor = "#92400e"
blueColor   = "#1e40af"
grayColor   = "#78716c"

[[theme.fontFaces]]
family = "Libre Baskerville"
url = "app/static/LibreBaskerville-Regular.woff2"
weight = 400
[[theme.fontFaces]]
family = "Libre Baskerville"
url = "app/static/LibreBaskerville-Bold.woff2"
weight = 700
[[theme.fontFaces]]
family = "IBM Plex Sans"
url = "app/static/IBMPlexSans-Variable.woff2"
weight = "100 700"
[[theme.fontFaces]]
family = "IBM Plex Mono"
url = "app/static/IBMPlexMono-Regular.woff2"
weight = 400

[server]
enableStaticServing = true
```

All three families are open (SIL OFL) and on Google Fonts; download the woff2 files into
`tempo/dashboard/static/`. The one permitted CSS injection is the eyebrow class (`font-mono text-xs
uppercase tracking-[0.2em] text-text-secondary`) applied through `st.html` to keyed containers.

### 5.2 Chart palette on paper

Validated with the dataviz palette checker on the `#fafaf8` surface, all pairs: charge green, discharge
orange and belief blue pass lightness, chroma, colour-vision-deficiency separation (worst pair ΔE 8.2),
normal-vision separation (worst 25.6) and 3:1 contrast. The brand green `#1a4d3e` and Toven's `#1e40af`
blue both failed (too dark, and the green reads grey at line weight), so they stay on buttons and text
only. Hold stone is deliberately grey and sits at 2.4:1, so a hold always carries its glyph and label.

| Role | Hex | Note |
|---|---|---|
| charge | `#1f8a5a` | lighter brand green; glyph ▲ |
| discharge / sell | `#c2410c` | burnt orange; glyph ▼ |
| hold | `#a8a29e` | stone; glyph — and label, never colour alone |
| forecast p50 + band | `#2563eb` | band at 18% opacity |
| actual price | `#1c1917` | ink, 2px |
| perfect foresight | `#78716c` dashed | |
| good / bad delta | `#15803d` / `#991b1b` | always with a sign character |
| now rule | `#1c1917` at 50% | |

---

## 6. Build order

| # | Step | Est. | Depends on |
|---|---|---|---|
| 1 | `web/` Next app: tokens, fonts, `Reveal`, `Eyebrow`, `Nav` (scroll state), `Footer`; deploy static export behind nginx on the backend box | 1.5 h | |
| 2 | Hero: settlement-grid SVG with pulses, h1/lead/button stagger, stat pills, sponsor rows | 1.5 h | 1 |
| 3 | Data hub card (`popIn` spokes, `flow` edges, `ping`), "How it works" three steps with their three illustrations | 3 h | 1 |
| 4 | Slides section: 700vh sticky, direction variants, dot rail, overview grid + 6 slides (illustrations can start as static SVG and gain motion later) | 3 h | 1 |
| 5 | Honesty tiles, final CTA, mobile pass at 390px (hero stacks, pills full-width, hamburger) | 1 h | 1 |
| 6 | Dashboard re-theme: `config.toml` + fonts + eyebrow helper; Report frame section order; stat pills; audit tiles with brand border | 2 h | ui.md steps 1–4 |
| 7 | Cross-links and nav parity between the two pages; record the backup video scrolling the pitch then the dashboard | 30 min | 1–6 |
| 8 | (If time) option B: port Live and Timing audit to React inside `web/app/app/` with FastAPI endpoints | 1.5 days | 6 |

Steps 1, 2, 5, 6, 7 are must-have for the pitch. 3 and 4 carry the "wow" and can ship with fewer slides.

---

## 7. Checks before calling it done

- Open the pitch page and the dashboard side by side: same nav, same paper, same serif, same green.
- `prefers-reduced-motion`: loops off, reveals still run once.
- Projector test: paper at `#fafaf8` is safe; check the `border-light` grid lines are still visible.
- No Toven string, logo or asset in `web/` (`grep -ri toven web/` is empty).
- Lighthouse on the static export: no layout shift from fonts (`next/font` handles the fallback metrics,
  as Toven's `Libre Baskerville Fallback` does).
