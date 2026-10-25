# Demo script

What to say on each chapter of the pitch site (`pitch/`, run with `cd pitch && npm run dev -- -p 3001`). The site shows only the charts, full screen. The words live here.

**Controls:** → or a click on the chart plays the next step. ← goes back one step. → after the last step opens the next chapter. The corner shows where you are ("2 / 5 · press →").

**Before you start:** run `make api` so the Live badge in the nav shows the current period and price. Without the API the badge hides itself, and everything else still works.

A chapter is added here once it is confirmed.

---

## 00 · Why this is hard (about 20 s)

**Headline:** Cheap at 3am. Expensive at 6pm. The hard part is *when*.

**In one line:** Electricity in Britain is priced every half hour. A battery makes money in between, but it has to commit before it knows the future.

| Step | On screen | Say |
|---|---|---|
| 1 | The price for 25 March 2026 draws itself, all 48 half-hours. Plays on arrival | "This is one real day of the British electricity market. Every half hour has its own price." |
| 2 | Two labels: **05:00 · 76% wind · −£5.24/MWh, paid to take power**, and **19:00 · everyone home · £136.50/MWh** | "At five in the morning the wind farms produce more than the country needs, and the price goes negative. You're *paid* to take power. At seven in the evening everyone's home, and it's £136. Same grid, same day, a £142 swing." |
| 3 | Charge window (04:00–05:30) in green, sell window (18:30–20:00) in amber, a battery filling, **£138.40/MWh spread** | "A battery makes money in between. It charges at the bottom and sells at the top. On this day that's a £138 spread." |
| 4 | A **NOW · 02:00** line. The rest of the day disappears, replaced by the range of prices at each hour over the previous 28 days, and a "?" | "But that's with hindsight. At 2am, you have to decide *now*, and tonight could be anywhere in this band. That's the hard part: not the price, the *timing*." |
| 5 | Three numbers count up: **66.4%** of perfect foresight · **£58,711** on 100 unseen weeks · **0** losing weeks | "Tempo makes that call every half hour. On 100 weeks it had never seen, it captured 66% of what perfect knowledge of the future would have made, and it never lost money in a week. Here's how." Then → to Data. |

**If asked**
- *Why this day?* It is the clearest real example of the pattern: a windy night with negative prices and an evening peak at dinner time. The numbers are read from Tiger (`prices_hh`, APX MID price), not drawn by hand.
- *What is the band in step 4?* The 10th to 90th percentile of the price at that half-hour over the previous 28 days. It's what you would have expected from recent history. The real night on 25 March was below the band, which is the point: history alone doesn't tell you.
- *Where do the step 5 numbers come from?* The walk-forward backtest, run `db-20261024T202144Z`, 100 weekly tests the model never trained on. The model is retrained before each week.
- *The Live badge?* The current settlement period and the latest price, read from Tiger through the API, refreshed every minute.

---

## 01 · Data (about 30 s)

**Headline:** Every row knows when it became available.

**In one line:** Official Elexon market data flows into Tiger hypertables, stamped with its publish time, so nothing from the future can leak into a decision.

| Step | On screen | Say |
|---|---|---|
| 1 | Elexon sources: **Prices**, **Wind forecast**, **Demand forecast**, and a dashed **+3 more** box. "6 datasets since Oct 2024 · 3 feed the model". Plays on arrival | "Everything starts with Elexon, the official feed for the British settlement system. Two years of history, six datasets. Three of them feed the model: prices, the wind forecast and the demand forecast." |
| 2 | The **Tiger** ring lights up, with data flowing in. **3,326,928 rows · 78% compressed**, and the tag **every row stamped available_at** | "It all lands in Tiger hypertables. 3.3 million rows, compressed by 78%. And every row is stamped with the moment it became *available*, not just the half-hour it describes. That one column is what makes everything after it honest." |
| 3 | Continuous aggregates: **35,074 half-hours → 732 days → 105 weeks** | "Tiger rolls it up automatically, half-hour to day to week, and keeps those rollups current as new data arrives." |
| 4 | **17 features · point-in-time** | "From that we build 17 features: yesterday's price, last week's, how windy tonight will be. Each one only uses data that was already published at the moment of the decision." |
| 5 | **LightGBM · p10 · p50 · p90 · trains in 92 s** | "LightGBM turns them into a forecast for the next 48 half-hours, with an uncertainty band. It trains in a minute and a half on a laptop." |
| 6 | **Optimiser** splitting into **Trade** (353 charge / sell) and **Hold** (943 on purpose). **1,296 live decisions** | "The optimiser turns the forecast into a decision. It knows the battery's limits and what each cycle costs. So far it has made 1,296 live decisions, and 943 of them were to hold, on purpose." |
| 7 | The **timeline** for 22 Oct 2026: every real publication as a dot (prices, wind forecasts, demand forecasts), a **Decision · 18:00** line, and a panel showing what that decision can see | "Here's what 'no peeking' means. This decision is at 6pm. It sees the 5:30 wind forecast for 7pm: 4,949 megawatts. It doesn't know the 7pm price; that arrives at 7:40." **Drag the line right to about 20:45:** "Move the clock on and the newer forecast appears, 4,690, and so does the real 7pm price, £206. A forecast released at 8:30 cannot touch a 6pm decision. 25 publications simply don't exist for it yet." Then → to Prediction. |

**Controls:** steps 1–6 advance with → or a click. On step 7 a click doesn't advance, so you can drag freely; → moves on.

**If asked**
- *How do you stop lookahead?* Wind and demand forecasts are read with `available_at <= decision time`. Prices have no publish time from Elexon, so each one is treated as available 10 minutes after its half-hour ends (a stated, cautious delay), and the feature code refuses to run if the stored delay ever differs from the configured one.
- *What are the other three datasets?* Generation mix (FUELHH), actual demand (INDO) and the system price (DISEBSP). They are loaded and stored with the rest but not used by the model yet. The generation mix gives the "76% wind" label on the opening chart. The system price was considered as Tempo's price and rejected: it is published about 24 hours late and isn't a price a battery can trade at.
- *Why is the wind forecast moving?* Elexon republishes it through the day. For 19:00 on 22 Oct it went from 6,706 MW (06:30) down to 4,690 MW (20:30). Each version is stored separately, so a replay sees the version that existed at the time.
- *Why 22 Oct?* It is the same day chapters 02 and 03 use, so the story follows one real day: what was known, what was forecast, what was decided.

---

## 02 · Prediction (about 30 s)

**Headline:** 28% less wrong than yesterday's prices.

**In one line:** LightGBM forecasts all 48 half-hours ahead with an uncertainty band, and beats the "same as yesterday" baseline on data it never saw.

| Step | On screen | Say |
|---|---|---|
| 1 | The live forecast made at **01:00 on 22 Oct**: a green line (the most likely price, p50) inside a shaded band (p10–p90). Plays on arrival | "This is what Tempo actually forecast at one in the morning on 22 October, for every half-hour of the next day. The line is its best guess; the band is how unsure it is." |
| 2 | **What actually happened** draws over it in blue | "And this is what really happened. It caught the morning rise and the evening peak. It got the midday dip wrong: prices fell further than it expected." |
| 3 | The comparison opens on **Same as yesterday**: a grey dashed line, amber sticks showing the error each half-hour, and the error bars. **Click LightGBM.** | "Is that good? Compare it to the simplest guess there is: tomorrow will be the same as today. Every amber line is how wrong that guess was." **Click LightGBM:** "Now our model. The lines get shorter. On 1,344 half-hours it never saw, it's off by £24 a megawatt-hour on average against £34. 28% less wrong." |
| 4 | **What the model leans on:** National demand forecast 22%, Wind share of demand 13%, Price this time yesterday 12%, Price this time last week 8%, Hour of day 8% | "And it learned the physics. The biggest signals are how much power the country will need and how much of it the wind will cover. Cold, still evenings make expensive electricity, and the model found that on its own." Then → to Decision. |

**Controls:** the toggle in step 3 switches between the two models and doesn't advance the step. → moves on.

**If asked**
- *Why this forecast?* It is a typical live run, not the best one. That day it was off by £21.4 against £33.0 for "same as yesterday". The best run (21 Oct, 19:00) was 18.2 against 31.8, and we chose not to lead with it.
- *The band misses a lot of the blue line.* Yes. It should contain about 80% of real prices; that day it contained 27 of 48, and across 405 settled live forecasts about 40%. The model is overconfident, and we say so (README, "What to improve"). Trades use only the middle line, so the band's width never changes a decision.
- *Where does 28% come from?* The training holdout: 1,344 half-hours after the training window. Mean absolute error £24.4 for LightGBM against £33.9 for persistence (same half-hour yesterday). 1 − 24.4 / 33.9 = 28%.
- *What do the feature percentages mean?* Each feature's share of the model's total gain: how much it improved the trees' splits during training. They show what the model relies on, not cause and effect.
- *Why LightGBM and not a neural network?* Gradient-boosted trees are strong on tabular data, train in about 90 seconds on a laptop CPU, and beat the baseline clearly. We climbed the model ladder only as far as the data justified.

---

## 03 · Decision (about 35 s)

**Headline:** It trades when it pays. It holds when it doesn't.

**In one line:** Every cycle has to cover efficiency losses and battery wear. If the spread falls short, Tempo holds, and says why.

This chapter uses the **next morning's live run: 07:00 on 23 October**, for the following 24 hours.

| Step | On screen | Say |
|---|---|---|
| 1 | The forecast price for each half-hour, coloured by decision: **charge** 11:30–12:30 (green), **sell** 17:00–18:30 (amber), **hold** everywhere else (grey). The battery level underneath. **7 trading · 41 holding · £189.01 expected**. Plays on arrival | "This is what Tempo decided at seven the next morning. Buy around lunchtime, when power is cheapest, sell into the evening peak, and hold for the other 41 half-hours. Holding is a decision too." |
| 2 | **Click a green bar** (e.g. 11:30), then **the 04:00 grey bar**. The card shows the real reason for each | "Every half-hour has a reason, logged with the decision. This one: buy now, sell at five. This grey one at 4am: the best trade it could find doesn't cover its costs." |
| 3 | **The trade it refused:** buy 04:00 at £119.45, sell 07:00 at £138.20. Waterfall: spread **£18.75** − efficiency loss **£13.82** − battery wear **£9.00** = **−£4.07 → HOLD** | "Here's the overnight trade it turned down. The price gap is £18.75. But 10% of the energy is lost on the round trip, and every cycle wears the battery. After both, it would lose £4 a megawatt-hour. So it holds. A system that only predicts prices would have taken that trade." |
| 4 | Sliders: **battery wear** (live £10/MWh) and **efficiency** (live 90%). **Drag wear down to £4:** the overnight cycle appears (10 trading, £201.10). **Drag it up to £16:** it only sells what's already stored (2 trading). **Click Reset.** | "These are the real optimiser's answers, not an animation. Make the battery cheaper to run and the overnight trade starts to pay, so it takes it. Make it dearer and it stops buying altogether; it only sells what it's already holding, because that energy is paid for." Then → to Proof. |

**Controls:** clicking bars (step 2) and the sliders (step 4) don't advance the step. → moves on.

**If asked**
- *Why a different day from Prediction?* On 22 October the price spreads were so large that no realistic cost changed the schedule. On the 23rd the cost gate is what decides, so it shows the decision logic honestly.
- *Was holding at 04:00 right?* On what Tempo knew, yes: the forecast was £119. The real 04:00 price turned out to be £50.58, so with hindsight that trade would have paid. That gap between a good decision and a lucky outcome is exactly what the timing audit (chapter 05) measures.
- *Are the sliders live?* They're the real `GreedyOptimiser`, run in advance on this exact forecast for every combination shown (155 runs), because the site is static. Re-running it on the stored forecast reproduces the live decisions exactly.
- *How are the costs worked out?* Per MWh bought, 90% comes back out (√0.9 in, √0.9 out). Efficiency loss is 10% of the sell price. Wear is £20 per full 2 MWh cycle, charged on the energy sold (£9 per MWh bought). A trade happens only if the spread beats both.
- *Why greedy and not the LP?* Both are built and backtested. The LP captured 68% of perfect foresight against greedy's 66% over 100 weeks. That wasn't enough to change the live decider the night before a demo. The LP is one flag away.
