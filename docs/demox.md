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
