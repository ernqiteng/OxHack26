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
