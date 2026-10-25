# Pitch site spec

What each chapter shows, agreed one at a time with Ayo before building. The presenter drives the demo; judges watch. Inputs only where they earn their place.

## 00 · Hook: "Why this is hard" (agreed, built, confirmed)

One real day of GB prices, revealed in five steps. The presenter presses → to advance each step.

- Day: **Wed 25 Mar 2026**. Low −£5.2/MWh at 05:00, peak £136.5/MWh at 19:00, spread £141.7. All 48 periods priced (APX MID, `prices_hh`).
- Steps:
  1. The 48-period curve draws left to right.
  2. The low and the peak get labels (time, reason, price).
  3. A battery appears: charge window green, sell window orange, spread arrow.
  4. A "now" line drops in at 02:00, and the curve to its right becomes an uncertain band: "you don't know tonight's price."
  5. Headline numbers count up: 66% of perfect foresight, £58.7k on 100 unseen weeks, 0 losing weeks.
- Live badge in a corner: "● LIVE · period N · £X/MWh" from the API. Hidden if the API can't be reached.
- No inputs.

## 01 · Data: "Where does it come from, and can you trust it?" (agreed, built, confirmed)

Version A only (no stats strip, no feature table).

- Beat 1, pipeline flow chart. Presenter presses → to light each stage, with dashes flowing into it: Elexon BMRS → Tiger hypertables (stamped with availability time) → continuous aggregates (half-hourly → daily → weekly) → 17 features → LightGBM → optimiser → decision. Each box carries one real number, read from Tiger at build time.
- Beat 2, "no peeking" timeline. Real publication events on a time axis, and a decision line at 18:00. Events published after the line turn grey and drop out of the feature list. Presenter drags the line.
- Line to say: "A forecast released at 7pm cannot touch a 6pm decision."

## 02 · Prediction: "Is the forecast any good?" (agreed, built, confirmed)

Version A, three steps. Calibration moves to 04 Proof.

- Day: the live forecast made at **01:00 BST Thu 22 Oct 2026** (`forecasts`, run_id 'live'), covering 22 Oct. That day: p50 error £21.4/MWh against £33.0 for persistence. It's a typical run, not the best (21 Oct 19:00 was 18.2 against 31.8).
- Step 1, fan chart: the p10–p90 band and the p50 line draw in. Press → and the actual prices draw over the top.
- Step 2, toggle "Same as yesterday" ⇄ "LightGBM": the forecast line morphs between the two. Two error bars beside the chart use the holdout numbers (1,344 unseen half-hours): £33.9 against £24.4, "28% less wrong". The day's own numbers go in a small caption.
- Step 3, what the model looks at: horizontal bars for the top 5 features by gain, in plain English. National demand forecast 22%, wind share of demand 13%, yesterday's price 12%, last week's price 8%, hour of day 8%.
- Only input: the toggle.

## 03 · Decision: "What did it actually do, and why?" (agreed, built, awaiting confirmation)

Version A, four steps. **Changed from 22 Oct to the 23 Oct 07:00 live run** (decision_id 1345–1392, agreed with Ayo): on 22 Oct the costs never change the schedule, and its "16p" hold wasn't decided by the cost gate. Re-running GreedyOptimiser on the stored forecast (start SoC 1.0 MWh) reproduces all 48 stored actions.

- Step 1, schedule: p50 price bars coloured by action (charge 11:30–12:30, sell 17:00–18:30, 41 holds) and a battery strip (0–2 MWh). 7 trading half-hours, 41 holding, expected £189.01 on the forecast.
- Step 2, reason card: the presenter clicks a bar. The reasons are the optimiser's own strings, converted to UK time (greedy.py prints UTC, e.g. "sale at 18:30" means 19:30 BST) and plain English by `_plain_reason` in scripts/export_pitch.py, which fails on any string it doesn't recognise.
- Step 3, the refused overnight cycle: decision 1386, buy 04:00 £119.45, sell 07:00 £138.20. Spread £18.75 − efficiency loss £13.82 − wear £9.00 = −£4.07, so HOLD.
- Step 4, what-if sliders: wear £0–30/MWh (live 10) and efficiency 75–95% (live 90). There are 155 precomputed runs of the real optimiser. Wear ≤ £4 brings the overnight cycle back (10 trading, £201.10). £12 shrinks the daytime cycle. ≥ £16 only sells the stored energy (2 trading, £181.42).
- To flag to Ernqi: greedy.py's reason strings print UTC times, and the old dashboard and API show them as they are.

## 04 · Proof: "Does it make money, compared with the alternatives?" (agreed)

Version A, three steps. "Where it's weak" (calibration, regime gap) is not on the site. It is in README.md under "What to improve".

- Step 1, strategy ladder: bars grow from worst to best, from the walk-forward backtest over 100 unseen weeks (run db-20261024T202144Z). Simple rule 33.1% £29,265 → persistence 52.9% £46,798 → **Tempo 66.4% £58,711** → Tempo LP 68.3% £60,391 → perfect 100% £88,388. Step labels: "+20 pts: forecasting beats a fixed schedule", "+13.5 pts with the same optimiser: that's the model", perfect = "the ceiling".
- Step 2, 100 weeks as dots by % of perfect, coloured calm/windy. Label the worst (31.2%) and best (90.2%). "Not one cherry-picked week."
- Step 3, replay: ▶ Play button with a 1×/4× switch. Windy week from 11 Jun 2026 (models/replay_week.*, median windy week, 62.9% of perfect). The price line runs, the battery charges and sells, and £ ticks up to £611 with perfect's total as the target.
- Inputs: Play and speed only.

## 05 · Timing: "Did it pick the right moment?" (agreed)

Version A, four steps. Bars for the verdict, not stacked timelines.

- Step 1, decision card: the decision chosen by `scripts/demo_reset.py` (reference run: #1353, charge 1 MW at 11:30 Thu 23 Oct 2026), its reason, and a big **Run timing audit** button.
- Step 2, live flow chart driven by the real audit (`POST /api/decisions/{id}/audit`, then polling): a Tiger fork box with a live timer, five lines fanning out to tempo-worker-1..5 labelled −1h, −30m, as decided, +30m, +1h. Each pulses while replaying and ticks ✓ when its result arrives. About 30–40 s (#1353 took 31 s).
- Step 3, verdict: five bars of £ against "as decided". For #1353: −£5.22, −£3.32, £0, −£20.33, −£34.81. Callout on the worst: "An hour later would have cost £34.81."
- Step 4, self-grade: "7 of 8 cycles timed within one half-hour of the best possible; mistiming cost £6.37 a cycle on average." Read live from the API when the page is built, since the counts change.
- Only input: Run. A small fork / in-process switch and a "show last recorded run" link (labelled as recorded) are the safety net.
- Built on two API endpoints (tempo/api/server.py): `POST /api/decisions/{id}/fork-audit` starts `AuditJob` (one at a time, one fork slot) and `GET` the same path polls `AuditProgress`. Tested live on 25 Oct: fork audit-1353-all, 5 Vultr workers, 39.2 s, fork deleted, the same numbers as the recorded run. `/timing?decision=N` audits the decision `demo_reset.py` picks.

## Look (agreed): toven.ai style

Colours sampled from toven.ai screenshots. All tokens are in app/globals.css. We reuse the style only, never Toven's logo or copy.

- Paper #fafaf8 page, white cards with a #d5d3d1 border, 16px radius, a faint inner grid (`.card-grid`) and a soft shadow.
- Ink #1b1917 headings in Libre Baskerville bold. Body #77716d in IBM Plex Sans. Eyebrow labels in IBM Plex Mono, uppercase, wide tracking.
- Brand green #284c3f (logo, Live pill, progress dots, the central node's ring).
- Diagram nodes: #f6f6f2 fill, #d8d6d4 border, thin grey curves (#b4b0ac). The central node is a double ring with a soft glow, like Toven's.
- Action colours, from Toven's status boxes: **charge = "cleared" green** (#74ca7e, ink #57905e, bg #f4fdf6, border #adefbc), **sell = "escalated" amber** (#ecaf56, ink #985f3c, bg #fefcef, border #f6db7a), **hold = grey** #b4b0ac.
- Layout: sticky nav (logo, chapter links, Live pill). Each chapter is text beside a card, alternating sides. Vertical progress dots on the right.
- Keys: ← / → move between chapters. Once a chapter has steps, → plays its next step first and only moves on after the last one.
- Pages (agreed): one page per chapter, not one long scroll. `/` hook, `/data`, `/prediction`, `/decision`, `/proof`, `/timing`. Nav links, progress dots, the footer "← prev · next →" links and the ← / → keys all change page. The nav underlines the current chapter. Chapter content lives in `app/<id>/page.tsx`, inside the shared `components/Chapter.tsx`.

## Data and running

- `python scripts/export_pitch.py [chapter]` writes the snapshot JSON in `pitch/data/` (read-only against Tiger). Re-run before a rehearsal.
- `make api` serves the live badge (CORS allows :3001). `cd pitch && npm run dev -- -p 3001` for the site.
- Steps: `lib/useSteps.ts`. Step 1 plays on arrival, → / click goes forward, ← goes back. The page changes only past the last or first step.

## After a chapter is confirmed (agreed)

1. Its words (headline, paragraph, what to say at each step, likely questions) move to `docs/demox.md`, the presenter script.
2. The page goes full screen: `<Chapter id=… full>`. No text column; the chart card fills the space between the nav and the footer, with only the chapter tag and the step caption inside it.

Done for: 00, 01, 02.
- Colour for **what actually happened** (agreed): blue #2563c9 (`--color-actual`), 3 px. It's the only blue on the site, so it never reads as a forecast (green) or an action or error (amber). Use it on every chart that shows real outcomes against a forecast.
