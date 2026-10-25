# Tempo

A battery trading system for the GB electricity market. Tempo forecasts half-hourly prices, decides when a grid battery should charge, sell or deliberately do nothing, and then proves, half-hour by half-hour, whether each decision was made at the right time.


| Presentation website | http://136.244.77.120/ — what Tempo is, how it works, and how it uses Tiger Data and Vultr |

| Pitch dashboard | http://136.244.77.120/app/ — the live demo: one real day of prices, the forecast, the decision, the proof and a live timing audit |

> "It's buy-low-sell-high for a battery. The hard part isn't the price. It's the timing."

### At a glance

- **66.4% of perfect foresight on 100 unseen weeks** (£58,711), 2× a fixed-hours rule and 13.5 points above a persistence forecast running the same optimiser.
- **Zero losing weeks.** The worst of the 100 still captured 31.2% of what was possible.
- **28% less wrong than "same as yesterday"**: £24.4/MWh mean error against £33.9 on 1,344 held-out half-hours.
- **Live, not a notebook.** A decision every 30 minutes from a Vultr box in London: 1,296 live decisions so far, 943 of them deliberate holds.
- **Timing proven, not claimed.** One click forks the live Tiger database and five Vultr workers replay the decision an hour early to an hour late, in parallel. On our demo decision, "as decided" beat all four alternatives.
- **No lookahead, enforced by tests.** Every row knows when it became available, and a test deletes each point-in-time filter in turn to prove the suite catches it.

---

## Contents

1. [What Tempo is](#1-what-tempo-is)
2. [Results](#2-results)
3. [How it works](#3-how-it-works)
4. [How Tempo fits the tracks](#4-how-tempo-fits-the-tracks)
5. [Challenges we hit](#5-challenges-we-hit)
6. [Known limits and what's next](#6-known-limits-and-whats-next)
7. [Architecture and tech stack](#7-architecture-and-tech-stack)
8. [Repo map](#8-repo-map)
9. [Run it yourself](#9-run-it-yourself)

---

## 1. What Tempo is

### The market

Great Britain's wholesale electricity market is settled in **48 half-hour settlement periods a day**, each with its own price. The shape of a day is predictable, but the size of the swings is not:

- At 3am on a windy night, wind farms generate more than the country needs and prices collapse, sometimes below zero.
- At 6pm on a cold weekday, everyone gets home and prices spike.

A grid battery makes money between those two moments: charge when power is cheap, discharge when it is expensive. The spread, minus losses, is profit.

### Why it's hard

1. **You have to predict the future.** Charging now is a bet on the next 24 hours of prices.
2. **The battery has physical limits.** Tempo's battery holds 2 MWh, moves 1 MW at a time and loses about 10% of the energy on every round trip, plus £20 of wear per full cycle.
3. **Doing nothing is a real decision.** On a flat day the spread doesn't cover the losses. The right call is to hold, and a system that can't hold bleeds money on calm days.

### What Tempo does

| Layer | What it does |
|---|---|
| **Live decision engine** | Every half hour: pull Elexon market data into Tiger Data, build point-in-time features, forecast the next 48 prices as a p10/p50/p90 band with LightGBM, and run a cost-gated optimiser that commits to charge, discharge or hold, with a written reason on every row |
| **Timing audit** | Click any decision and Tempo replays it 1 hour early, 30 minutes early, on time, 30 minutes late and 1 hour late, inside one Tiger Data zero-copy fork, on five Vultr workers in parallel. It shows in pounds what rushing or hesitating would have cost |
| **Honesty panel** | Walk-forward results on weeks the model never saw, against honest baselines, as a share of perfect foresight. Plus calibration, a calm-vs-windy breakdown and where the model is weak, on screen at all times |

Most prediction projects stop at an accuracy number. Tempo turns the prediction into a constrained decision, measures the decision in pounds on unseen data, and then checks whether it was made at the right *time*.

---

## 2. Results

Walk-forward backtest over **100 unseen weeks** (24 Oct 2024 to 24 Oct 2026, run `db-20261024T202144Z`): 28 days of training, retrained for every 7-day test week, each week scored against perfect foresight on that same week.

| Strategy | Money made | % of perfect foresight |
|---|---|---|
| Simple rule (charge 1am to 5am, sell 5pm to 7pm) | £29,265 | 33.1% |
| Persistence forecast + same greedy optimiser | £46,798 | 52.9% |
| **Tempo** (LightGBM + greedy, what runs live) | **£58,711** | **66.4%** |
| Tempo LP (LightGBM + LP optimiser) | £60,391 | 68.3% |
| Perfect knowledge of the future | £88,388 | 100% |

- **The model earns its place.** Persistence uses the same optimiser as Tempo, so the 13.5-point gap between them is the value of the forecast alone.
- **Consistent, not lucky.** Tempo never loses money in a week (worst 31.2%, best 90.2%). The simple rule lost money in 17 weeks.
- **No strategy beats perfect foresight in any week**, which is the sanity check that nothing peeks at the future.
- **% of perfect foresight** is the headline because raw pounds swing between calm and volatile weeks: a windy week can be worth five times a calm one. A share of the theoretical maximum makes weeks comparable.

**The timing audit on a real decision (#1353, charge 1 MW at 11:30 on 23 Oct):**

| 1 h earlier | 30 min earlier | **As decided** | 30 min later | 1 h later |
|---|---|---|---|---|
| −£5.22 | −£3.32 | **£0** | −£20.33 | −£34.81 |

One Tiger fork, five Vultr workers, 32 seconds, equal to the in-process replay to the penny. Across every completed live cycle, Tempo's own self-grade puts its timing within one period of the best moment on 7 of 8 (mean cost of mistiming £6.37).

---

## 3. How it works

```
Elexon Insights API  (6 datasets: MID prices, WINDFOR, NDF, INDO, FUELHH, DISEBSP)
        │  2-year backfill + live poller (every 60 s, fetches only datasets that changed)
        ▼
Tiger Data hypertable grid_raw  (every row stamped with available_at)
        │
continuous aggregates  prices_hh → prices_daily → prices_weekly
        │
build_features(decision_time)  (only rows with available_at ≤ decision_time)
        │
LightGBM × 3 quantile models  → 48 half-hourly prices as p10 / p50 / p90
        │
cost-gated optimiser (greedy live, cvxpy LP in the backtest)  → charge / discharge / hold + reason
        │
forecasts + decisions hypertables  (48 rows per batch, every 30 min, on the Vultr backend box)
        │
        ├──────────────────────────────┐
        ▼                              ▼
dashboards                       timing audit (on click)
(live, replay, honesty)                │
                                 1 Tiger zero-copy fork of live data
                                       │
                                 5 Vultr workers replay shifts −2 / −1 / 0 / +1 / +2 in parallel
                                       │
                                 side-by-side £ comparison, fork deleted
```

### 3.1 Ingest: Elexon → Tiger Data ([`tempo/ingest/`](tempo/ingest/))

- Source: the free **Elexon Insights API**, the official GB balancing and settlement feed.
- Six datasets: APX Market Index Data (MID) prices, wind forecast (WINDFOR), national demand forecast (NDF), outturn demand (INDO), generation by fuel (FUELHH) and system prices (DISEBSP). 3.3 million rows over two years.
- A two-year **backfill** loads history through Elexon's stream endpoints. A **metadata-driven poller** checks `/datasets/metadata/latest` every minute and refetches only the datasets that moved.
- **Point-in-time stamping starts here.** Every row stores `available_at`: Elexon's publish time where it has one, or period end + 30 min + a stated 10-minute delay for MID, which has none. Rows are keyed on the API's UTC `startTime`, so clock-change days (46 or 50 periods) need no special case.

### 3.2 Features with no lookahead ([`tempo/features/build.py`](tempo/features/build.py))

- `build_features(conn, decision_time)` uses only data with `available_at ≤ decision_time`. A wind forecast published one minute after the decision can't be used.
- 17 features: price lags (same period yesterday and last week), daily and weekly spreads and volatility from the continuous aggregates, wind and demand forecasts (forward-filled, never interpolated, because interpolating would need a forecast that may not be published yet), and UK-local calendar features.
- Every point-in-time filter is one SQL line ending in `-- pit`. [`tests/contracts/test_pit_leak.py`](tests/contracts/test_pit_leak.py) deletes each one in turn, and the suite must fail every time.

### 3.3 Quantile forecast ([`tempo/forecast/lgbm.py`](tempo/forecast/lgbm.py))

- Three LightGBM regressors with `objective='quantile'` (α = 0.1, 0.5, 0.9) predict each of the next 48 half-hours. Outputs are sorted per row so p10 ≤ p50 ≤ p90 always holds.
- Model ladder, simplest first: **persistence** (same price as yesterday) is the baseline LightGBM had to beat, and it did, by 28%.
- It learned the physics on its own: the national demand forecast and wind share of demand are its two biggest features.
- Training is deterministic and takes about 90 seconds on a laptop CPU. We tested a Vultr NVIDIA A16: 1.6× faster, no better forecasts, so the live system stays CPU-only.

### 3.4 Cost-gated decision ([`tempo/optimise/`](tempo/optimise/), [`tempo/sim/battery.py`](tempo/sim/battery.py))

- **Battery:** 2 MWh capacity, 1 MW power, 90% round-trip efficiency, £20 wear per full cycle. `simulate()` is the single source of truth for physics and P&L.
- **Cost gate:** a buy/sell pair is traded only if `eff·sell − buy > eff·wear per MWh`, the exact condition under which `simulate()` shows a profit. Otherwise Tempo **holds** and logs why. A real example it refused: an £18.75 spread, minus £13.82 of efficiency loss and £9.00 of wear, is −£4.07, so it held.
- **Greedy optimiser (live):** repeatedly pairs the cheapest buy period with the dearest later sell period and moves as much energy as the battery allows.
- **LP optimiser:** a `cvxpy` linear program over all 48 periods with state-of-charge, power, efficiency and wear constraints. It beat greedy by two points over 100 weeks; not enough to swap the live system the night before the demo, so it sits on the honesty table and is one flag away (`--optimiser lp`).

### 3.5 Timing audit ([`tempo/audit/`](tempo/audit/), [`tempo/worker/main.py`](tempo/worker/main.py))

1. **Click a decision.**
2. Tempo takes **one Tiger Data zero-copy fork** of the live database: a writable copy, frozen at the click.
3. The orchestrator sends five timelines (the batch shifted −2, −1, 0, +1, +2 periods) to **five Vultr workers in parallel**. Each worker connects to the fork, replays the battery at actual prices and writes its own battery state under its own run id.
4. All five appear side by side with the real decision highlighted and a sentence like "an hour later would have cost £34.81".
5. The fork is deleted. Only the results are kept.

A **self-grade** ([`tempo/audit/selfgrade.py`](tempo/audit/selfgrade.py)) runs the same shift analysis on every completed cycle and reports how often Tempo's timing was within one period of the best shift.

### 3.6 Honesty and walk-forward backtest ([`tempo/backtest/`](tempo/backtest/))

- Test weeks tile the range, each preceded by its own training window, never overlapping. Every week starts from a fresh battery.
- Strategies only see test-week prices that were already published at decision time. Perfect foresight is the only strategy allowed to see them all.
- The honesty panel shows the results table, calibration of the p10–p90 band, the calm-vs-windy breakdown and plain statements of where Tempo is weak, including the ones that don't flatter it.

### 3.7 What you see

- **[Presentation website](http://136.244.77.120/):** the pipeline, Tiger Data and Vultr explained with animated diagrams.
- **[Pitch dashboard](http://136.244.77.120/app/):** six full-screen chapters driven with the arrow keys. **Hook** (one real day of prices), **Data** (a draggable timeline showing what a decision could and couldn't see), **Prediction** (the live forecast against what happened), **Decision** (every half-hour's reason, and what-if sliders running the real optimiser), **Proof** (all 100 weeks and a replayed windy week) and **Timing** (a live fork audit). Every number is read from Tiger, not drawn by hand.

---

## 4. How Tempo fits the tracks

### HRT: Best Use of Data for Predictions and Decision Making

Grid data in, a proven decision out, every 30 minutes. HRT separates a model that predicts from an optimisation step that turns predictions into actions under constraints; Tempo has exactly those two parts, and it follows the research habits HRT writes about.

**01 · Decisions, not just predictions**
- A quantile forecaster feeds a constrained optimiser with real battery physics
- Holding is a decision too: 943 of 1,296 live decisions were deliberate holds, each with its reason
- The decision is measured in pounds, not in accuracy

**02 · No lookahead, proven**
- Every row stamped with `available_at`: when Tempo could first have seen it
- Features use only rows with `available_at ≤ decision_time`
- Each filter is tagged `-- pit`; a test removes each one and must fail

**03 · Don't fool yourself**
- Walk-forward: retrained every week, tested only on weeks it never saw
- Honest baselines: a fixed rule, a persistence forecast on the same optimiser, and the perfect-foresight ceiling
- The replay shows the *median* windy week, chosen by rule, not the best one

**04 · Simple first**
- Persistence had to be beaten before LightGBM earned its place
- Greedy stays live because the LP's two-point gain didn't justify the swap
- A GPU trained 1.6× faster and forecast no better, so it isn't used

**05 · Show the bad numbers**
- The p10–p90 band holds 40% of real prices, not 80%: overconfident, and on screen
- We expected forecasting to help more in windy weeks; it didn't, and the panel says so

### Best Use of Tiger Data

Tiger Data is Tempo's only database, and both the feature pipeline and the signature mechanic depend on it.

| Feature | How Tempo uses it |
|---|---|
| Hypertables | `grid_raw` (two years of Elexon data plus every new half-hour), `forecasts` and `decisions` (48 rows every half hour), audit results |
| Continuous aggregates | Half-hourly → daily → weekly prices, each built on the level below. They feed the model's features and the charts, and update themselves as new prices land |
| Compression | 3.3 million rows, 78% compressed, inside the 750 MB free tier. The two-year price query executes in 19 ms |
| Zero-copy forks | The engine of the timing audit: a writable copy of the live database, frozen at the click, that five replays can write into without touching live |

**Why the fork is load-bearing.** The five what-if timelines each need to *write* their own battery state and P&L, not just read the past, against data frozen at the moment of the click. A fork gives exactly that. On a free service it is copy-on-write and ready in 36–42 seconds; a standard fork takes 5–20 minutes, too slow for a live click.

### Best Use of Vultr

Tiger supplies the data forks; Vultr supplies the machines that replay against them.

| Feature | How Tempo uses it |
|---|---|
| Cloud compute | Five `vc2-1c-1gb` workers in New Jersey (beside Tiger's us-east-1), a 2 GB backend in London, and an NVIDIA A16 rented by the minute |
| Snapshots | One bootstrapped image, cloned into every worker |
| Instance tags | `tempo-worker` marks the pool; anything untagged is never dispatched to |
| v2 API | Create, list, lease and tear down the fleet from Python |

**01 · Five workers replay in parallel**
- One click sends five shifted timelines to five workers at once
- Pre-warmed all day: a cold boot takes 39 s to active and 78 s to SSH, too slow for a click
- Each worker is a stateless FastAPI app: `POST /replay` returns the P&L, guarded by a bearer token

**02 · Lease-based scheduling**
- Workers are found through the Vultr API by tag; idle means active with no lease held
- One job per worker, always released; if workers are busy, jobs queue

**03 · Snapshot to fleet in one command**
- `build_worker_image.py` bootstraps a box, verifies `/health` and the token, snapshots it and deletes it
- `create_workers.py` clones five workers from the snapshot; `create_backend.py` sets up the London box that runs the poller, the decider every 30 minutes and both websites

**04 · A GPU by the minute, to answer one question**
- `gpu_box.py` creates an NVIDIA A16 in `lhr`, checks `nvidia-smi` and `torch.cuda`, and deletes it
- The A16 is easy to miss: `GET /v2/plans?type=vcg` doesn't list it; only `type=all` does
- 500 models in 17.4 s on the A16 against 28.0 s on the same box's CPU: faster, but no better forecasts, so the live system stays CPU-only. Total cost: $1.44

---

## 5. Challenges we hit

- **Five forks became one.** We designed one zero-copy fork per timeline. On real Tiger, the third fork was refused with `403 ENTITLEMENT_ERROR`: a free project holds only two services, and paid forks take minutes. Tempo now takes one fork per click with all five timelines under separate run ids, and a test proves the result is identical to the penny in both layouts.
- **A 750 MB database that was already half full.** An empty free-tier database already reported 339 MB used. Mid-backfill we paused with 1.4 million rows to go, changed the loader to compress after every window instead of every dataset, and resumed the same evening. All six datasets now take about 65 MB.
- **Elexon's sharp edges.** Prices have no publish time, so we state a cautious delay and wait for it. Settlement periods are numbered in UK local time, so we key everything on UTC; the clocks went back during the hackathon and the poller handled a real 50-period day live.
- **We caught ourselves in-sample.** Our first back-dated live batches were made by a model trained on later prices. The features were point-in-time; the model wasn't. We relabelled those batches, added a training cut-off and regenerated them out-of-sample, and published the less flattering numbers that followed.
- **A bug hiding in a 0.1 kW sale.** A property-based test caught the LP overfilling the battery after a tiny-flow clean-up. Fixed, with a regression test.

---

## 6. Known limits and what's next

| Limit | Next step |
|---|---|
| The p10–p90 band holds 40% of prices, not 80%. Trades use p50, so it never changes a decision | Recalibrate on recent residuals, then let the LP's conservative mode (buy at p90, sell at p10) use it |
| Forecasting helps no more in windy weeks than calm ones | Use the actual demand and generation-mix data already stored in Tiger |
| Tempo captures 66.4% of perfect foresight | Promote the LP (68.3%) once more live weeks confirm its lead |
| One fork per click on the free tier | Five forks, one per timeline, is already in the code behind one setting |
| The backtest runs on one machine in about 7 minutes | Split the 100 independent weeks across the Vultr workers and measure the speed-up |

Tempo assumes the battery can trade at the APX Market Index price each period. System price publishes about 24 hours late, so it can't drive live decisions.

---

## 7. Architecture and tech stack

```
                       Elexon Insights API
                               │
              ┌────────────────▼─────────────────┐
              │ tempo-backend  (Vultr, London)   │
              │  poller        every 60 s        │──────┐
              │  decider       every 30 min      │      │ reads / writes
              │  API + nginx   websites          │      ▼
              └────────────────┬─────────────────┘   Tiger Data free service (us-east-1)
                               │ audit click            primary  ──fork──▶  audit fork
                               ▼                                               ▲
              tempo-worker-1..5 (Vultr, New Jersey) ── POST /replay ──────────┘
```

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| Database | Tiger Data (TimescaleDB on PostgreSQL): hypertables, continuous aggregates, compression, zero-copy forks |
| Data | pandas, NumPy, pyarrow, psycopg 3 |
| Forecasting | LightGBM quantile regression, scikit-learn |
| Optimisation | Greedy pairing (custom), cvxpy linear program |
| Data source | Elexon Insights API |
| Compute | Vultr cloud compute (v2 API), Ubuntu 24.04, systemd, nginx |
| Services | FastAPI + Uvicorn (workers and API), Streamlit (ops dashboard) |
| Websites | Next.js 15 (static export), React 19, Tailwind CSS 4, Motion |
| Testing | pytest, hypothesis, respx, freezegun, local TimescaleDB in Docker; 463 tests passing |

---

## 8. Repo map

```
tempo/            the Python package
  ingest/         Elexon client, backfill, live poller
  features/       point-in-time feature builder
  forecast/       quantile LightGBM, persistence baseline
  optimise/       cost gate, greedy, LP, perfect foresight
  sim/            battery physics and P&L
  decide/         run_decision(), the live pipeline
  backtest/       walk-forward backtest and honesty metrics
  audit/          timing audit, worker pools, self-grade
  infra/          Tiger Cloud and Vultr API clients
  worker/         FastAPI replay worker
scripts/          backfill, train, decide, backtest, Vultr fleet and GPU scripts
tests/            unit, contract, database and live tests
presentation/     the presentation website
pitch/            the pitch dashboard
deploy/           systemd units, nginx config, bootstrap
docs/             design notes, plans and the demo script
```

---

## 9. Run it yourself

The live system needs Tiger Data and Vultr credentials, but the tests and both websites run locally.

```bash
make setup                                  # venv and dependencies
make test                                   # unit + contract tests, no network, no DB

cd presentation && npm install && npm run dev            # http://localhost:3000
cd pitch && npm install && npm run dev -- -p 3001        # http://localhost:3001
```
