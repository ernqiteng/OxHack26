# Tempo

A battery trading system for the UK electricity market. Tempo forecasts half-hourly prices, decides when a grid battery should charge, sell, or deliberately do nothing, and then proves, half-hour by half-hour, whether it picked the right moment.

Built for OxHack 2026. Theme: **TIME**. Track: **HRT, Best Use of Data for Predictions and Decision Making**. Built on Tiger Data and Vultr.

> "It's buy-low-sell-high for a battery. The hard part isn't the price. It's the timing."

---

## 1. What Tempo is

### The market

Great Britain's wholesale electricity market is settled in 48 half-hour blocks per day, called settlement periods. Each one has its own price. Those prices swing hard and predictably in shape, but not in size:

- At 3am on a windy night, wind farms are generating more than the country needs. Prices collapse, sometimes below zero.
- At 6pm on a cold weekday, everyone arrives home, turns on the heating and the oven, and prices spike.

A grid-scale battery makes money by sitting between those two moments. It charges when electricity is cheap and discharges back into the grid when electricity is expensive. The difference, minus losses, is profit.

### The decision problem

That sounds simple, and the naive version is. The real problem has three parts that make it genuinely hard:

1. **You have to predict the future.** You commit to charging now based on what you believe prices will do over the next 24 hours. If you charge at 2am and the real low is at 4am, you paid too much.
2. **The battery has physical limits.** It can only hold so much energy, charge and discharge so fast, and it loses energy every cycle. You cannot simply "buy all the cheap periods and sell all the expensive ones."
3. **Doing nothing is a real decision.** On a flat day, the gap between cheap and expensive may not cover the energy lost in a round trip plus the wear on the cells. The right call is to hold, and a system that cannot hold will bleed money on calm days.

Tempo treats all three as the core of the product. It forecasts, it optimises under constraints, it explicitly chooses to hold when the edge is not there, and it then audits whether each decision was taken at the right moment.

### The one-sentence pitch

Electricity in Britain is priced every half hour, cheap at 3am when it's windy and expensive at 6pm when everyone gets home. Tempo forecasts those prices, decides when a battery should charge, sell or deliberately do nothing, and then proves whether each decision was made at the right time by replaying it in parallel timelines shifted earlier and later, showing in pounds what rushing or hesitating would have cost.

---

## 2. Why not just predict a price?

The obvious data-and-prediction hackathon project is "an AI that predicts whether a stock or crypto price goes up." Almost every such entry shows an accuracy number on a random train/test split, with no baseline, no transaction costs, and no evidence that a single decision made with that prediction was any good.

Tempo avoids that trap in two ways.

**A different market.** Electricity is a real, noisy, real-time market with real money in it, and judges will not have seen it at every hackathon. More importantly, it has hard physical constraints. A battery can only hold so much, charge so fast, and loses energy every cycle. Those constraints turn a prediction problem into an actual decision problem, which is what the HRT track is asking for.

**Proof, not claims.** Tempo does not report "92% accuracy." It reports money made on weeks the model never saw, against honest baselines, as a percentage of the best result that was theoretically possible with perfect knowledge of the future. And it audits whether each decision's timing was right.

We are not trying to build the best price forecaster in the room. We are trying to be the only team that can show, mechanically and live, that its decisions were good and that they were made at the right time.

---

## 3. What we're building

Tempo has three layers. Together they are the whole pitch.

### Layer 1: Live decision engine

This is the pipeline from raw market data to a committed battery action.

#### Data in

- **Source:** the Elexon BMRS API, the official data feed for the GB balancing and settlement system. It is free and needs no API key.
- **What we pull:** prices per settlement period, wind generation forecasts, national demand, and the generation mix by fuel type.
- **Cadence:** 48 settlement periods a day, so new data arrives during the demo and the live view genuinely updates.
- **History:** a bulk load of around two years of history for training and backtesting.

Everything lands in **Tiger Data hypertables**. Every row is stamped with the time the data became *available*, not just the settlement period it *describes*. Elexon provides a publish time for the wind forecast, demand forecast, generation mix and system price, and we store it as-is. The Market Index Data price series carries no publish time, so for those rows we store a stated availability delay (period end plus a fixed number of minutes, shown on the honesty panel). This matters more than anything else in the data layer: it guarantees no lookahead. When Tempo makes a decision for 6pm, every feature it uses is built only from data that had actually been available at the moment the decision was made. A wind forecast released at 7pm cannot leak into a 6pm decision.

**Price series.** Tempo uses APX Market Index Data (the within-day exchange index) as its price. System price is published about 24 hours after the period it describes, so it cannot drive live decisions. The N2EX index has frequent zero-price, zero-volume rows. We assume the battery can transact at the APX index price for each period, and that assumption is stated on screen.

#### Features

Features are built from **hierarchical continuous aggregates** at three timescales:

| Timescale | Examples |
|---|---|
| Half-hourly | Price at the same settlement period yesterday and last week, forecast wind as a share of demand (the wind forecast is hourly and is interpolated to settlement periods), time-of-day effects |
| Daily | Rolling daily price spread (max minus min), daily mean, day-of-week effects |
| Weekly | Weekly volatility, regime indicators (calm vs windy) |

The same aggregates that feed the model also drive the dashboard charts, and they stay current automatically as new settlement periods arrive.

#### Forecast

The forecaster predicts the price for each of the next 48 settlement periods. It does not output a single number per period. It outputs three quantiles, **p10, p50 and p90**, so the system knows how confident it is. The decision layer uses that uncertainty: a wide band means a smaller expected edge, which can tip a marginal cycle into a hold.

We use a model ladder and climb it only as far as the data justifies, simplest first:

1. **Persistence.** "The price at this half-hour will be the same as yesterday." This is the baseline every real model has to beat.
2. **LightGBM.** Gradient-boosted trees. Strong on tabular data, fast to train, and the model that does the job.

#### Decision

The battery is a simulated grid-scale unit with realistic parameters:

| Parameter | Value |
|---|---|
| Capacity | 2 MWh |
| Max charge / discharge rate | 1 MW |
| Round-trip efficiency | ~90% |
| Degradation cost | Fixed cost per full cycle |

The decision layer is **cost-gated**. Tempo only commits to a cycle when the expected spread, after the ~10% efficiency loss and the per-cycle degradation cost, is positive. If it is not, Tempo explicitly **holds**, and the hold is logged as a decision in its own right, with the reason attached ("expected spread £X did not cover £Y in losses").

Two versions of the optimiser:

- **Version 1, greedy rule.** Charge in the cheapest predicted periods, discharge in the most expensive, within the capacity and rate limits. Simple, fast, and a solid fallback.
- **Version 2, linear program.** A `cvxpy` LP that maximises expected profit over the 48-period horizon subject to every battery constraint: state-of-charge bounds, charge and discharge rate limits, efficiency losses, and degradation cost.

**What runs live: the greedy rule.** Both optimisers are built, tested and in the walk-forward backtest with the same LightGBM forecast. Over 100 unseen weeks the LP captured 68% of perfect foresight and greedy 66%. Two points was not enough to swap the live decider the night before the demo, and it follows the simple-first rule we hold ourselves to: prefer the simpler method unless the complex one is clearly better. Both rows are on the honesty table so the judges can see the gap themselves. The LP is one flag away (`scripts/decide.py --optimiser lp`) and is the obvious next step with more data.

Every decision, whether charge, discharge or hold, is written to a **decisions hypertable** along with its timestamp and the full forecast it was based on. That record is what the timing audit replays.

### Layer 2: Timing audit (the signature mechanic)

This is the part that answers the TIME theme directly. A prediction can be right while the decision made from it is badly timed. Tempo measures that gap.

Click any decision on the dashboard and Tempo:

1. **Spawns five alternative timelines.** The same action, shifted by −2, −1, 0, +1 and +2 settlement periods. In other words: what if we had done this an hour earlier, half an hour earlier, exactly when we did, half an hour later, or an hour later?
2. **Takes a Tiger Data zero-copy fork of the live database at the moment of the click.** The fork is an isolated, writable copy of everything Tempo knew at that instant. All five what-ifs run inside it, each writing its own simulated battery state and profit-and-loss under its own run id, so they never touch the live system or each other. This is the honest reason the fork is load-bearing: five parallel what-ifs that each need to *write* state, not just read the past, against a frozen copy of the live data. The live database runs as a Tiger free service, where a fork is copy-on-write and was ready in 36 to 42 seconds in our tests. On a standard service a fork takes 5 to 20 minutes, which would be too slow for a live click. (We first designed one fork per timeline; see section 11 for why it is one fork per click.)
3. **Dispatches the five replays to a pre-warmed pool of Vultr workers in parallel.** Each worker, provisioned via the Vultr API, takes one timeline, connects to the fork and replays the battery forward from that point.
4. **Shows all five side by side** on the dashboard, with the real decision highlighted and a concrete number attached: *"charging one period later would have cost £14."*

The same shift analysis also runs automatically on every completed charge-discharge cycle, as in-process backtest shifts rather than a fork, which gives Tempo a running self-grade. Forks are reserved for the on-stage audit:

> "Tempo's timing was within one settlement period of hindsight-optimal on 71% of cycles this month."

That line is the product's own honest scorecard on the one thing it exists to do: choosing *when*.

### Layer 3: Honesty, on screen at all times

Tempo never hides its evaluation. The honesty panel is a permanent part of the dashboard.

#### Walk-forward backtest

The model is trained on a window of history and then tested on the weeks that follow, which it has never seen. The window rolls forward and the process repeats. Results are reported against three baselines:

| Strategy | Money made | % of perfect foresight |
|---|---|---|
| Simple rule ("charge 1am to 5am, sell 5pm to 7pm") | £A | a% |
| Persistence forecast + same optimiser | £B | b% |
| **Tempo** (LightGBM forecast + same optimiser) | £C | c% |
| Perfect knowledge of the future | £D | 100% |

The baselines matter. The simple rule tests whether forecasting adds anything over a fixed schedule. The persistence row isolates the value of the model from the value of the optimiser, because both use the same optimiser. Perfect foresight sets the ceiling.

#### Headline metric: % of perfect-foresight profit captured

Raw pounds vary wildly between a calm week and a volatile one. A system can make £500 in a windy week and £40 in a flat one and be performing identically. Reporting profit as a share of the theoretical maximum makes weeks comparable and makes the number honest.

#### Also on screen

- **Calibration.** Does the p10–p90 band actually contain about 90% of real prices? If the band contains 60%, the model is overconfident and the cost gate is being lied to.
- **Regime breakdown.** Performance split into calm weeks vs windy, volatile weeks. Prediction tends to matter far more in the second.
- **Where it's weak.** If the simple rule nearly matches Tempo in summer, when spreads are small, we show that too. The point of the panel is that a judge can see the limits without having to ask.

---

## 4. End-to-end data flow

```
Elexon BMRS API (APX MID prices, wind forecast, demand, generation mix)
        │  every settlement period + 2 years of history
        ▼
Tiger Data hypertables  (raw data, stamped with availability time)
        │
hierarchical continuous aggregates (half-hourly → daily → weekly)
        │
feature pipeline (only data available before decision time)
        │
forecaster on Vultr  → 48-period price quantiles (p10 / p50 / p90)
        │
battery optimiser (greedy live; cvxpy LP as a backtest row), cost-gated: charge / discharge / hold
        │
decision + forecast + timestamp written to decisions hypertable
        │
        ├────────────────────────────┐
        ▼                            ▼
honesty dashboard             timing audit
(backtest table,              (click or automatic)
 calibration,                        │
 regime breakdown)            one Tiger Data zero-copy fork
                              of live data, taken on click
                                     │
                              5 Vultr workers replay shifts
                              −2 / −1 / 0 / +1 / +2 in parallel
                                     │
                              side-by-side £ comparison
                              + running self-grade
```

---

## 5. Why each tool is load-bearing

### Tiger Data

- **Hypertables** for the grid data stream and the decisions log. Time-series storage that is built for exactly this shape of data: a high-frequency append-only stream queried by time range.
- **Free service as the primary database.** Free services use copy-on-write storage, which is what makes forks zero-copy and fast enough to create on a click.
- **Hierarchical continuous aggregates** for multi-timescale features and live dashboard charts. The half-hourly, daily and weekly rollups update themselves as new data arrives.
- **Compression** on two years of history, shown on screen ("X million rows, compressed Y%"), with a two-year query returning instantly.
- **Zero-copy forks** as the timing-audit engine. The what-if timelines need a writable copy of the live database, frozen at the moment of the click, that they can scribble on without touching live. Nothing in Layer 2 works without it.

Take Tiger Data away and both the feature pipeline and the signature mechanic go with it.

### Vultr

- **Parallel replay workers** for the timing audit, provisioned via the Vultr API. Judges watch five workers each pick up a timeline, replay it against the fork and return results live.
- **Parallel walk-forward backtests**, with a reported speed-up over running them in sequence.
- **Model training** on CPU. GPU plans are not available to this account (every Vultr GPU plan reports no locations, checked via the API), and LightGBM on tabular features does not need one.
- **Battery-size sweep** (stretch): re-running the backtest across different battery capacities is a naturally parallel workload.
- **Backend and dashboard hosting**, the least interesting part.

The timing audit doesn't happen without Vultr compute provisioned on demand.

---

## 6. Demo script (3 minutes)

| Time | Section | What happens |
|---|---|---|
| 20s | Hook | "Electricity is cheap at 3am and expensive at 6pm. A battery can make money in between. The hard part is *when*." |
| 35s | Live view | Current settlement period, next 24h forecast with uncertainty bands, today's schedule, and a recent hold with its reason: "expected spread didn't cover the 10% efficiency loss." |
| 50s | Replay | Rewind to a windy week, play it forward: forecast vs reality, battery charging and selling, £ ticking up. |
| 40s | Timing audit | Click a decision. Tiger forks the live database, five Vultr workers replay five timelines in it in parallel, side-by-side result: "an hour later would have cost £31." Then the running self-grade. While the fork spins up (~40 s), tell the challenge from section 11. |
| 30s | Honesty panel | Backtest table, % of perfect foresight, calibration, plain statement of where it's weak. If asked why the LP row beats the live Tempo row: "two points over a hundred weeks, simple first, it's one flag to switch." |
| 5s | Close | "Most projects stop at a prediction. We turned it into a decision, and then proved whether we made it at the right time." |

---

## 7. Build plan

Cut from the bottom if time runs out.

### Must-have (the whole pitch on its own)

1. Elexon history (via the stream endpoints, which are not capped at 7 days) and live polling into Tiger Data hypertables, with continuous aggregates at two timescales (weekly if time allows).
2. Walk-forward backtest with the greedy rule, the simple-rule baseline and perfect foresight. This alone is a demo.
3. LightGBM forecast feeding the cost-gated decision, and the backtest table on screen.

### Should-have

4. Timing audit as plain backtest shifts first, then moved into Tiger Data forks with Vultr workers.
5. Running self-grade and the live decisions view.
6. Quantile forecasts and the calibration chart.

### Nice-to-have (cut first)

7. `cvxpy` LP optimiser. Built, tested, and in the backtest as the Tempo LP row (68% vs greedy's 66%). Greedy stays live, see section 3.
8. Battery-size sweep and regime breakdown.
9. pgvector "similar days" lookup, finding historical days whose shape matches today's forecast.

---

## 8. Phase gates

Checkpoints instead of clock times, so the plan holds whatever the final schedule is.

| Gate | Done when | Decisions made here |
|---|---|---|
| **Gate 0: Setup** (first hour) | Repo, Tiger Data free service, Vultr account, Elexon pull tested | Price series is APX Market Index Data (system price publishes ~24h late, N2EX has frequent zero rows). Fix the MID availability delay. Vultr GPU: checked, not available on this account, CPU only. Vultr instance limit checked. Who owns what. |
| **Gate 1: Data** | History loaded, live polling running, aggregates building | Confirm availability-time stamping on every row |
| **Gate 2: Baseline demo** | Backtest table with simple rule, greedy + persistence, perfect foresight | Lookahead sanity check: only perfect foresight should "know" the future |
| **Gate 3: Tempo decides** | LightGBM forecast feeding the cost gate, Tempo row in the table | |
| **Gate 4: Timing audit** | Shifts as backtest, then forks + Vultr workers | Pre-warm worker pool, rehearse click sequence |
| **Gate 5: Polish** | Self-grade, quantiles, calibration, stretch items | What to cut. Record a backup run of the full demo. |
| **Gate 6: Freeze** | Nothing new. Rehearse the 3 minute script twice. | |

---

## 9. Known risks

| Risk | Handling |
|---|---|
| Live fork and worker provisioning on stage | Pre-warm the Vultr pool, trigger real API calls against warm instances, rehearse the clicks, keep a recorded run as backup and present it as "a run from earlier today" |
| Model only slightly beats the simple rule | Fine. % of perfect foresight keeps it interesting, and showing where prediction helps and where it doesn't is what HRT respects |
| Wrong price series | APX Market Index Data, decided. Filter out N2EX rows. Don't switch |
| Lookahead bugs | Publish-time stamp on every row where Elexon provides one, stated availability delay for MID, features only from data available before decision time, check that only perfect foresight knows the future |
| Vultr account instance limit | Request an increase at Gate 0. Fall back to fewer workers; the pool queues the five timelines across whatever workers exist |
| Forks too slow on the day | Primary database is a free service (forks ready in 36 to 42 s in testing). If still slow, pre-create the fork before the demo and have the click dispatch workers into it, or switch the toggle to in-process ("same replay, run locally") |
| Tiger free tier allows only 2 services | Audit uses one fork per click (section 11). Nobody creates other forks on demo day; `demo_reset.py` checks only the primary exists. The audit button is disabled while an audit runs |
| Unfamiliar domain for judges | Open with the buy-low-sell-high line |
| Vultr GPU not available (confirmed: no GPU plan has any location for this account) | Train on CPU, lean on parallel workers as the Vultr story, never say "GPU" on stage |

---

## 10. Why this wins

### TIME

Time is the subject of the product, not a label on it.

- Prices change every half hour.
- Features are built at three explicit timescales.
- Every row carries the time it became available, so the system can prove it never used the future.
- The battery's whole job is choosing *when*.
- The signature mechanic asks whether each decision was made at the right time by running it earlier and later in parallel timelines and pricing the difference.

### HRT track: Best Use of Data for Predictions and Decision Making

The track rewards decisions, not just predictions. HRT's own writing on AI in trading separates a model that predicts from an optimisation step that turns predictions into actions under constraints (HRT: *Applying AI to Trading*). Tempo has exactly those two parts: a quantile forecaster and a constrained optimiser.

It also follows the research habits HRT writes about publicly:

- **Simple first.** Prefer the simpler model if it's as good (HRT: *ML benchmarks*). LightGBM is the forecaster: on tabular features, gradient-boosted trees are the right tool. The greedy optimiser stays live because the LP's two-point gain over 100 weeks did not justify the swap; the LP sits on the honesty table as a row, not in production.
- **Don't fool yourself.** Low signal-to-noise domains make it easy to see edges that aren't there. We test only on unseen weeks against honest baselines.
- **No lookahead.** Availability-time stamping on every row (HRT: *How HRT Thinks About Data*).

What sets it apart:

- It decides, not just predicts, including holding when the edge doesn't cover costs.
- It proves its decisions in pounds, on unseen data, as a share of the theoretical maximum.
- It proves its timing live, with a reproducible mechanism rather than a claim.

### Vultr

Parallel workers that judges watch pick up timelines and return results, parallel walk-forward backtests with a reported speed-up, and model training. The timing audit doesn't happen without Vultr compute provisioned on demand.

### Tiger Data

Hypertables for the grid stream and the decisions log, hierarchical continuous aggregates for features and charts, compression for two years of history, and a zero-copy fork as the engine of the timing audit. Take Tiger Data away and both the feature pipeline and the signature mechanic go with it.

---

## 11. Challenges we hit (say these in the pitch)

Judges ask "what went wrong?". These are true, specific, and show we tested against the real services rather than the brochure.

### Tiger's free tier allows only two databases, so five forks became one

**What we planned.** One zero-copy fork per timeline: five forks of the live database spun up on the click, each replayed by its own Vultr worker.

**What happened.** When we ran it against real Tiger, the third service was refused with `403 ENTITLEMENT_ERROR: "You have reached your free service limit"`. A free Tiger project holds two services at once, the live database plus one fork. The fast copy-on-write forks only exist on free services (paid-service forks take 5 to 20 minutes), so paying would not have helped.

**What we did.** One fork per click, frozen at the moment of the click, with all five timelines replayed inside it in parallel by five Vultr workers. Each timeline writes its own battery state under its own run id, so they stay isolated from each other and from live. We proved the change costs nothing in correctness: an automated test shows the fork replay equals the in-process replay to the penny, in both the one-fork and five-fork layouts. The five-fork layout is still in the code behind one setting (`TEMPO_AUDIT_FORKS=per_shift`) for an account with a higher limit.

**What it taught us.** The limit also means nothing else may hold a Tiger service during the demo, and a second click must wait for the first audit to finish. The pre-demo check and a disabled button handle both.

**Pitch line (~10 s, say it while the fork spins up):**

> "We designed this as five forks, one per timeline. When we ran it on real Tiger we hit the free tier's two-database limit, and paid forks take minutes, not seconds. So Tempo takes one fork of live data the moment you click, and five Vultr workers replay five timelines inside it in parallel. We have a test proving it gives exactly the same numbers to the penny."
