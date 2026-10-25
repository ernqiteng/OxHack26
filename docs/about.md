## Inspiration

Electricity in Great Britain is priced every half hour. At 3am on a windy night, wind farms produce more than the country needs and the price collapses, sometimes below zero. At 6pm on a cold weekday, everyone gets home, switches on the oven and the heating, and the price spikes. A grid battery makes money in the gap between those two moments.

The theme was **TIME**, and this felt like the most literal version of it we could find. A battery doesn't really need to know *what* the price will be. It needs to know *when* to act. Charge an hour too early and you overpay. Sell an hour too late and the peak has gone.

We were also building for HRT's track, **Best Use of Data for Predictions and Decision Making**. The obvious hackathon project in that space is "a model that predicts whether a price goes up", usually reported as an accuracy number on a random train/test split. We wanted the opposite: a system that turns a forecast into a constrained decision, measures that decision in pounds on data it has never seen, and then checks whether the decision was made at the right time.

## What it does

Tempo has three layers:

1. **A live decision engine.** Every half hour it pulls Elexon market data into Tiger Data, forecasts the next 48 prices as a $p_{10}/p_{50}/p_{90}$ band, and commits to *charge*, *discharge* or *hold* for each period, with a written reason on every row.
2. **A timing audit.** Click any decision and Tempo replays it one hour early, half an hour early, on time, half an hour late and one hour late, in parallel, and shows in pounds what rushing or hesitating would have cost.
3. **An honesty panel.** Results on weeks the model never saw, against honest baselines, as a share of what perfect knowledge of the future would have earned.

## How we built it

### Data: Elexon → Tiger Data

We pull six datasets from the Elexon Insights API (prices, wind forecast, demand forecast, outturn demand, generation mix and system prices) with a two-year backfill and a live poller. Everything lands in **Tiger Data** hypertables, rolled up by continuous aggregates into half-hourly, daily and weekly prices, with compression keeping two years of history inside the free tier.

The most important design decision in the whole project was **point-in-time stamping**. Every row stores `available_at`, the moment Tempo could first have seen it. A feature for a decision at time $t$ is built only from

$$
\mathcal{D}(t) = \{\, r : \texttt{available\_at}(r) \le t \,\}.
$$

The price series we use (APX Market Index Data) has no publish time, so we state one conservatively:

$$
\texttt{available\_at} = \texttt{start\_time} + 30\ \text{min} + 10\ \text{min}.
$$

Every point-in-time filter in the SQL is tagged `-- pit`. A test deletes each one in turn, and the test suite has to fail every time. If it doesn't, the filter wasn't doing anything.

### Forecast: quantile LightGBM

Three LightGBM models predict each of the next 48 half-hours, one per quantile $\alpha \in \{0.1, 0.5, 0.9\}$, each trained on the pinball loss

$$
L_\alpha(y, \hat y) = \max\big(\alpha\,(y - \hat y),\ (\alpha - 1)\,(y - \hat y)\big).
$$

Quantile models are fitted independently, so their outputs can cross. We sort them per row so that $p_{10} \le p_{50} \le p_{90}$ always holds. We climbed the model ladder simplest first: a persistence baseline ("same price as yesterday") had to be beaten before LightGBM earned its place.

### Decision: a cost-gated optimiser

The simulated battery holds $E = 2$ MWh, moves $P = 1$ MW, has round-trip efficiency $\eta = 0.9$, and costs $c = £20$ of wear per full cycle. Each half-hour period trades at most $e = P \times 0.5\,\text{h}$, and the efficiency loss is split evenly between charging and discharging:

$$
\text{SoC}_{t+1} =
\begin{cases}
\text{SoC}_t + e\sqrt{\eta} & \text{charge} \\
\text{SoC}_t - e / \sqrt{\eta} & \text{discharge}
\end{cases}
\qquad 0 \le \text{SoC} \le E.
$$

A buy/sell pair only makes money if the spread beats the efficiency loss and the wear, so Tempo trades only when

$$
\eta\, p_{\text{sell}} - p_{\text{buy}} > \eta \cdot \frac{c}{E}.
$$

Otherwise it **holds** and logs why. On a flat day, doing nothing is the right decision, and a system that can't hold bleeds money.

We built two optimisers. The live one is a greedy rule that repeatedly pairs the cheapest buy period with the dearest later sell period. The second is a `cvxpy` linear program over the full 48-period horizon:

$$
\max_{c_t,\, d_t \ge 0}\ \sum_{t=1}^{48} 0.5\, p^{(50)}_t\,(d_t - c_t)\ -\ 0.5\, w \sum_{t=1}^{48} d_t
$$

where $c_t$ and $d_t$ are charge and discharge power and $w = c/E$ is wear per MWh discharged, subject to the state-of-charge, power and efficiency constraints above.

### Timing audit: Tiger forks and Vultr workers

When you click a decision, Tempo takes a **Tiger Data zero-copy fork** of the live database: a writable, copy-on-write copy frozen at that instant. It then sends five timelines, the same schedule shifted by $k \in \{-2, -1, 0, +1, +2\}$ half-hours, to **five pre-warmed Vultr workers in parallel**. Each worker is a small FastAPI service that connects to the fork, replays the battery at actual prices and returns its profit. The audit reports

$$
\Delta_k = \text{PnL}(k) - \text{PnL}(0),
$$

the cost of acting $k$ periods early or late. The same analysis runs automatically on every completed cycle as a self-grade: Tempo's timing counts as "within one period" when $\arg\max_k \text{PnL}(k) \in \{-1, 0, +1\}$.

A separate Vultr box in London runs the poller, the live decider every 30 minutes, and the Streamlit dashboard.

### Measuring it honestly

We ran a walk-forward backtest: 28 days of training, retrained for every 7-day test week, over 100 unseen weeks. Raw pounds swing wildly between calm and volatile weeks, so the headline metric is the share of perfect foresight captured:

$$
\text{score} = \frac{\sum_{w} \text{PnL}^{\text{Tempo}}_w}{\sum_{w} \text{PnL}^{\text{perfect}}_w}.
$$

| Strategy | Money made | % of perfect |
|---|---|---|
| Fixed rule (charge 1–5am, sell 5–7pm) | £29,265 | 33.1% |
| Persistence forecast + same optimiser | £46,798 | 52.9% |
| **Tempo** (LightGBM + greedy, live) | **£58,711** | **66.4%** |
| Tempo LP (LightGBM + LP) | £60,391 | 68.3% |
| Perfect foresight | £88,388 | 100% |

The persistence row uses the same optimiser as Tempo, so the gap between them isolates the value of the model itself.

**Stack:** Python, Tiger Data (TimescaleDB), LightGBM, cvxpy, pandas, FastAPI, Streamlit, Vultr, and a Next.js presentation site.

## Challenges we ran into

**Five forks became one.** We designed the audit as one Tiger fork per timeline. When we ran it against the real service, the third fork was refused with `403 ENTITLEMENT_ERROR: "You have reached your free service limit"`: a free Tiger project holds only two services at once, the live database plus one fork. Paying wouldn't have helped, because the fast copy-on-write forks only exist on free services, and paid forks take 5–20 minutes. We redesigned the audit around one shared fork per click, with each timeline writing under its own run id. Measured: the fork is ready in 36–42 s, and the five replays add 1.3 s. A test proves the result is identical to the penny in both layouts.

**A 750 MB database that was already half full.** The free tier caps storage at 750 MB, and an *empty* database already reported 339 MB used. Midway through the two-year backfill we had to stop with one dataset (the national demand forecast) at 4 of 13 windows: the loader only compressed after a whole dataset finished, so the remaining 1.4 million rows would have sat uncompressed and pushed the database past the cap, which makes it read-only for everyone. We changed the loader to compress after every window and resumed it from its log the same evening. Along the way we learned that Tiger enforces the cap on its own storage metric, not on `pg_database_size`: at the pause one said 515 MB and the other 147 MB. Compressed, all six datasets (3.3 million rows) take about 65 MB, roughly 14 bytes a row.

**Elexon's data has sharp edges.**
- The Market Index price has no publish time, so we state an availability delay and wait for it.
- The N2EX price index is full of zero-price, zero-volume rows. We use APX, and still drop its zero-volume rows: there were 12 in a single year.
- Settlement periods are numbered in UK local time. Computing one from the UTC clock is off by two every day in summer time, and on the last clock-change day it got all 50 periods wrong. We key everything on the UTC start time instead, and the clocks went back during the hackathon itself, so the poller saw a real 50-period day live.
- The demand-forecast endpoint rejects windows longer than one day, so the poller fetches it day by day.

**Lookahead is easy to introduce and hard to see.** Interpolating an hourly wind forecast to 10:30 quietly uses the 11:00 forecast, which may not exist yet at decision time. We forward-fill instead. That's why we built the leak test that deletes each point-in-time filter and expects the test suite to fail.

**A bug hiding in a 0.1 kW sale.** A property-based test caught the LP optimiser overfilling the battery. It sold a sliver of energy it already held (0.00006 MWh), then charged to exactly full. The clean-up step that zeroes sub-kilowatt flows dropped the sale but kept the charge, so the battery went over capacity. Each period is now trimmed to what the battery can physically do after that clean-up, with a regression test for the case.

**Cold starts are too slow for a live click.** A new Vultr instance took 39 seconds to boot and 78 seconds to accept SSH. So the five workers run all day, built from one snapshot, and a click only has to find them through the Vultr API by tag. A simple lease-based scheduler keeps it to one job per worker and queues the rest.

**A GPU check that was wrong.** On day one, the Vultr API seemed to say no GPU was available: the GPU plan listing showed every plan with no locations. The next day we found an NVIDIA A16 listed only under the full plan list, available in London. We rented three short-lived A16 boxes, about 29 minutes in total ($1.44), to answer one question: training 500 models took 17.4 s on the GPU against 28.0 s on the same box's CPU, about 1.6× faster, but the forecasts were no better. So the live system stays CPU-only.

**Three people, one schema, three laptops.** We split the work three ways: data, model and optimiser, and the audit plus the dashboard. To work in parallel, we froze the database schema and the interfaces between modules on day one and built against a synthetic dataset until the real data landed. Deploying taught us the same lesson: the deploy script ships whatever is on the deployer's laptop, so a deploy from a branch that hadn't merged a teammate's work quietly rolled it back. We now deploy only from an up-to-date `main`.

## Accomplishments that we're proud of

- **It's live, not a notebook.** A Vultr box in London polls Elexon every minute and commits a fresh 48-period schedule a minute past every half hour, writing to Tiger Data with no laptop involved. At the time of writing it had made 1,296 live decisions, 943 of them deliberate holds.
- **It beats honest baselines on unseen data.** Over 100 weeks the model never saw, Tempo captured 66.4% of perfect foresight (£58,711): 2× a fixed-hours rule, and 13.5 points above a persistence forecast running the same optimiser, so those points belong to the model. It never lost money in a single week (worst 31.2%, best 90.2%), while the fixed rule lost money in 17 of them.
- **The forecast is 28% less wrong than "same as yesterday".** On 1,344 held-out half-hours, LightGBM's $p_{50}$ was off by £24.4/MWh on average against £33.9 for persistence. Without being told, it learned that demand and wind share drive the price: they are its two biggest features.
- **The timing audit works end to end.** One click takes a Tiger zero-copy fork and replays five timelines on five Vultr workers in parallel. On our demo decision (#1353) it took 32 seconds and found that Tempo's timing was the best of the five: an hour later would have cost £34.81. The result matches the in-process replay to the penny. On every completed live cycle, the self-grade puts Tempo's timing within one period of the best moment 7 times out of 8.
- **Two years of data, small and fast.** 3.3 million rows across six datasets, compressed by 78%, inside a free tier, with the two-year price query executing in 19 ms on Tiger.
- **We can prove there's no lookahead.** Every row carries the time it became available. The leak test fails if any single point-in-time filter is removed, and the backtest's feature code fails on each of three deliberately planted leaks.
- **Every decision explains itself.** All 48 rows in every batch, trades and holds alike, carry a plain-English reason, such as the overnight trade it refused: an £18.75 spread minus £13.82 of efficiency loss and £9.00 of wear is −£4.07, so it holds.
- **Every number has a test behind it.** 463 tests pass, including property-based tests on the battery physics and known-answer tests on every number a judge reads.
- **We published our weak spots.** The honesty panel shows the overconfident uncertainty band and the regime result that went against our expectations, right next to the headline number.

## What we learned

- **Point-in-time data is everything, and the model has to be point-in-time too.** A backtest is only as honest as its timestamps. We learned the second half the hard way: our first live decisions were back-dated batches made by a model trained on prices from after them. Every feature was point-in-time, but the model had already seen the answers. When we caught it, the band's coverage fell from 77% to 40%, the self-grade from 8 of 8 to 7 of 8, and our demo decision had to change. We relabelled the batches rather than deleting them, added a training cut-off (`train.py --until`), and regenerated them out-of-sample.
- **A decision is not a prediction.** Physical constraints and costs turn a good forecast into a much harder problem, and a cost gate that can say "hold" was worth as much as a better model. It also separates a good decision from a lucky outcome: the 04:00 trade Tempo refused would have paid with hindsight, because the real price came in at £50.58 against a £119 forecast. Holding was still right on what it knew, and the timing audit exists to measure exactly that gap.
- **Simple first, and mean it.** The LP beat greedy by two points over 100 weeks. That wasn't enough to justify swapping the live system the night before the demo, so the LP sits on the honesty table as a row instead. The same rule kept us off the GPU: it trained 1.6× faster and forecast no better.
- **Measure in pounds, as a share of what was possible.** A windy week can be worth five times a calm one, so raw profit hides whether the strategy did well. Dividing by perfect foresight makes weeks comparable, and comparing against a persistence forecast on the same optimiser tells you how much of the result is the model.
- **Choose the evidence by rule, not by hand.** The replay shows the median windy week (62.9% of perfect), not the best one. The forecast we present is a typical live run, not the best (£21.4 off against a best of £18.2). A highlight reel would have looked better and taught nobody anything.
- **Show the bad numbers too.** Our $p_{10}$–$p_{90}$ band should contain about 80% of real prices. On 405 live forecasts it contains 40%, so the model is overconfident. Trades use $p_{50}$ only, so the band never changes a decision, and the dashboard says so plainly. We also expected forecasting to matter more in windy weeks, and it didn't: Tempo's lead over persistence is 16 points on calm weeks and 12 on windy ones. Both findings are on screen.
- **Test against the real service, not the brochure.** The free-tier fork limit, the storage cap measured on a different metric from the database's own, and the GPU hiding in a different API listing all only showed up when we ran the real thing.

## What's next for Tempo

- **Run the backtest on the Vultr fleet.** The 100 test weeks are independent, so they can be split across the five workers. We want to add a `/backtest` endpoint next to `/replay`, prove the parallel run matches the sequential one row for row, and report a measured speed-up rather than an estimate.
- **Battery-size sweep.** Re-run the backtest for 1, 2, 4 and 8 MWh to show how much a bigger battery is worth under the same strategy.
- **Fix the overconfident band.** Recalibrate the $p_{10}$–$p_{90}$ interval so it really contains about 80% of prices, then let the uncertainty shape decisions: the LP's conservative mode already prices buys at $p_{90}$ and sells at $p_{10}$, ready to switch on once the band can be trusted.
- **Promote the LP.** With more live weeks behind it, switch the decider to the LP if it keeps its lead. It's one flag away (`--optimiser lp`).
- **One fork per timeline.** On a Tiger account with a higher service limit, the original five-fork layout is already in the code behind one setting (`TEMPO_AUDIT_FORKS=per_shift`).
