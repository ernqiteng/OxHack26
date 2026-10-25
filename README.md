# Tempo

A battery trading system for the GB electricity market. Tempo forecasts half-hourly prices, decides when a grid battery should charge, sell or deliberately do nothing, and then proves, half-hour by half-hour, whether each decision was made at the right time.

Built at OxHack 2026. Theme: **TIME**.

| | |
|---|---|
| Live dashboard | http://136.244.77.120:8501 (Streamlit on the `tempo-backend` Vultr box, London) |
| Presentation website | [`presentation/`](presentation/), run it with `cd presentation && npm install && npm run dev` ([details](#presentation-website)) |
| Pitch dashboard | http://136.244.77.120/app/ (what "Open the app" opens), source in [`pitch/`](pitch/): the chapter-by-chapter demo site the presenter drives ([details](#pitch-dashboard)); script in [docs/demox.md](docs/demox.md) |

> "It's buy-low-sell-high for a battery. The hard part isn't the price. It's the timing."

## Contents

1. [What Tempo is](#what-tempo-is)
2. [Main features](#main-features)
3. [Results](#results)
4. [How it works](#how-it-works)
5. [How Tempo fits the tracks](#how-tempo-fits-the-tracks)
6. [Tech stack](#tech-stack)
7. [Architecture and deployment](#architecture-and-deployment)
8. [Repo structure](#repo-structure)
9. [Running it locally](#running-it-locally)
10. [Deploying to Vultr](#deploying-to-vultr)
11. [Presentation website](#presentation-website)
12. [Pitch dashboard](#pitch-dashboard)
13. [Demo day: go/no-go check](#demo-day-gono-go-check)
14. [Challenges and known limits](#challenges-and-known-limits)
15. [What to improve](#what-to-improve)
16. [Docs](#docs)
17. [Team](#team)

---

## What Tempo is

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

Tempo has three layers:

| Layer | What it does |
|---|---|
| **Live decision engine** | Every half hour: pull Elexon market data into Tiger Data, build point-in-time features, forecast the next 48 prices as a p10/p50/p90 band with LightGBM, and run a cost-gated optimiser that commits to charge, discharge or hold, with a written reason on every row |
| **Timing audit** | Click any decision and Tempo replays it 1 hour early, 30 minutes early, on time, 30 minutes late and 1 hour late, inside one Tiger Data zero-copy fork, on five Vultr workers in parallel. It shows in pounds what rushing or hesitating would have cost |
| **Honesty panel** | Walk-forward results on weeks the model never saw, against honest baselines, as a share of perfect foresight. Plus calibration, a calm-vs-windy breakdown and where the model is weak, on screen at all times |

Most prediction projects stop at an accuracy number. Tempo turns the prediction into a constrained decision, measures the decision in pounds on unseen data, and then checks whether it was made at the right *time*.

---

## Main features

- **Live decisions every 30 minutes.** A 48-period forecast and a charge, discharge or hold decision for each period, made on the Vultr backend box and written to Tiger Data.
- **Price forecasts with uncertainty.** LightGBM quantile models give a p10/p50/p90 band for the next 24 hours, not a single guess.
- **Cost-gated trading.** Tempo trades only when the spread beats the 10% round-trip loss plus wear. Otherwise it holds and says why.
- **Every decision explained.** Each of the 48 rows in a batch carries a plain-English reason, for trades and holds alike.
- **No lookahead, proven by tests.** Every row is stamped with when it became available, and a test deletes each point-in-time filter in turn to prove it matters.
- **Timing audit.** Click any decision to replay it 1 hour early to 1 hour late in a Tiger Data fork, on five Vultr workers in parallel, priced in pounds.
- **Self-grade.** Every completed cycle is replayed at shifted times to score how often Tempo's timing was within one period of the best.
- **Honesty panel.** Walk-forward results on 100 unseen weeks against honest baselines, calibration, a calm-vs-windy breakdown and the model's weak spots.
- **Replay week.** Play a windy week forward on the dashboard: forecast against reality, battery charging and selling, £ ticking up.
- **Go/no-go check.** One script checks Tiger, forks, prices, decisions and workers before a demo and picks the decision to click.
- **Presentation website.** A static site explaining the pipeline, Tiger Data and Vultr with animated diagrams.

---

## Results

Walk-forward backtest over **100 unseen weeks** (24 Oct 2024 to 24 Oct 2026, run `db-20261024T202144Z`): 28 days of training, retrained for every 7-day test week, each week scored against perfect foresight on that same week.

| Strategy | Money made | % of perfect foresight |
|---|---|---|
| Simple rule (charge 1am to 5am, sell 5pm to 7pm) | £29,265 | 33.1% |
| Persistence forecast + same greedy optimiser | £46,798 | 52.9% |
| **Tempo** (LightGBM + greedy, what runs live) | **£58,711** | **66.4%** |
| Tempo LP (LightGBM + LP optimiser) | £60,391 | 68.3% |
| Perfect knowledge of the future | £88,388 | 100% |

- Tempo makes **2× the simple rule** and beats the persistence forecast with the same optimiser, so the gain comes from the model, not the optimiser.
- No strategy beats perfect foresight in any week (Tempo's best week is 90.2%), and Tempo never loses money in a week (worst 31.2%).
- **% of perfect foresight** is the headline metric because raw pounds swing between calm and volatile weeks. A share of the theoretical maximum makes weeks comparable.

---

## How it works

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
Streamlit dashboard              timing audit (on click)
(live, replay, honesty)                │
                                 1 Tiger zero-copy fork of live data
                                       │
                                 5 Vultr workers replay shifts −2 / −1 / 0 / +1 / +2 in parallel
                                       │
                                 side-by-side £ comparison, fork deleted
```

### 1. Ingest: Elexon → Tiger Data ([`tempo/ingest/`](tempo/ingest/))

- Source: the free **Elexon Insights API**, the official GB balancing and settlement feed. No API key.
- Six datasets: APX Market Index Data (MID) prices, wind forecast (WINDFOR), national demand forecast (NDF), outturn demand (INDO), generation by fuel (FUELHH) and system prices (DISEBSP).
- A two-year **backfill** ([`scripts/backfill.py`](scripts/backfill.py)) loads history through Elexon's stream endpoints. A **metadata-driven poller** ([`scripts/poll.py`](scripts/poll.py)) checks `/datasets/metadata/latest` and refetches only the datasets that moved. Both use the same `normalise()` and idempotent upsert.
- **Point-in-time stamping starts here.** Every row stores `available_at`: Elexon's publish time where it has one, or period end + 30 min + a stated 10-minute delay for MID, which has none. Rows are keyed on the API's UTC `startTime`, so clock-change days (46 or 50 periods) need no special case.

### 2. Features with no lookahead ([`tempo/features/build.py`](tempo/features/build.py))

- `build_features(conn, decision_time)` uses only data with `available_at ≤ decision_time`. A wind forecast published one minute after the decision can't be used.
- Features: price lags (same period yesterday and last week), rolling daily and weekly spreads and volatility from the continuous aggregates, wind and demand forecasts (forward-filled, never interpolated, because interpolating would need a forecast that may not be published yet), and UK-local calendar features.
- Every point-in-time filter is one SQL line ending in `-- pit`. [`tests/contracts/test_pit_leak.py`](tests/contracts/test_pit_leak.py) deletes each one in turn, and the suite must fail every time.

### 3. Quantile forecast ([`tempo/forecast/lgbm.py`](tempo/forecast/lgbm.py))

- Three LightGBM regressors with `objective='quantile'` (α = 0.1, 0.5, 0.9) predict each of the next 48 half-hours. Outputs are sorted per row so p10 ≤ p50 ≤ p90 always holds.
- Model ladder, simplest first: **persistence** (same price as yesterday) is the baseline that LightGBM has to beat.
- Training is deterministic (seed 0, one thread) and takes about 90 seconds on a laptop CPU. No GPU: gradient-boosted trees on tabular features don't need one.

### 4. Cost-gated decision ([`tempo/optimise/`](tempo/optimise/), [`tempo/sim/battery.py`](tempo/sim/battery.py))

- **Battery:** 2 MWh capacity, 1 MW power, 90% round-trip efficiency, £20 wear per full cycle. `simulate()` is the single source of truth for physics and P&L.
- **Cost gate:** a buy/sell pair is traded only if `eff·sell − buy > eff·wear per MWh`, the exact condition under which `simulate()` shows a profit. Otherwise Tempo **holds** and logs why, for example "expected spread £X did not cover £Y in losses".
- **Greedy optimiser (live):** repeatedly pairs the cheapest buy period with the dearest later sell period and moves as much energy as the battery allows.
- **LP optimiser (backtest row):** a `cvxpy` linear program over all 48 periods with state-of-charge, power, efficiency and wear constraints. It has a conservative mode that buys at p90 and sells at p10.
- Greedy stays live because the LP's two-point gain over 100 weeks didn't justify the swap. It's one flag away: `scripts/decide.py --optimiser lp`.
- [`scripts/decide.py`](scripts/decide.py) runs `run_decision()` a minute after every half hour and writes 48 `forecasts` rows and 48 `decisions` rows sharing one `decided_at`.

### 5. Timing audit ([`tempo/audit/`](tempo/audit/), [`tempo/worker/main.py`](tempo/worker/main.py))

1. **Click a decision** on the dashboard.
2. Tempo takes **one Tiger Data zero-copy fork** of the live database, ready in about 40 seconds. It's a writable copy, frozen at the click.
3. The orchestrator sends five timelines (the batch shifted −2, −1, 0, +1, +2 periods) to **five Vultr workers in parallel**. Each worker connects to the fork, replays the battery at actual prices and writes its own `battery_state` under its own run id.
4. The dashboard shows all five side by side with the real decision highlighted, for example "charging one period later would have cost £14".
5. The fork is deleted. Only the `audits` rows are kept.

A **self-grade** ([`tempo/audit/selfgrade.py`](tempo/audit/selfgrade.py)) runs the same shift analysis in-process on every completed cycle and reports how often Tempo's timing was within one period of the best shift, plus the average cost of mistiming.

### 6. Honesty and walk-forward backtest ([`tempo/backtest/`](tempo/backtest/))

- Test weeks tile the range, each preceded by its own training window, never overlapping. Every week starts from a fresh battery.
- Strategies only see test-week prices that were already published at decision time. Perfect foresight is the only strategy allowed to see them all.
- The dashboard's honesty panel shows the results table, calibration of the p10–p90 band, the calm-vs-windy regime breakdown and plain statements of where Tempo is weak.

### The dashboard ([`tempo/dashboard/app.py`](tempo/dashboard/app.py))

One Streamlit report page, in demo order:

- **Live:** the current period, the 24-hour forecast band, today's schedule and recent holds with reasons.
- **Replay:** a windy week played forward, forecast against reality, with £ ticking up.
- **Timing audit:** the click-to-fork, five-timeline comparison. A toggle switches between "Tiger fork + Vultr workers" and in-process.
- **Honesty:** the backtest table, calibration, regime breakdown and weak spots.
- **About**

Every section reads from Tiger. If a table is empty, it falls back to synthetic data and says so.

---

## How Tempo fits the tracks

These match the points on the [presentation website](#presentation-website).

### HRT: Best Use of Data for Predictions and Decision Making

Grid data in, a proven decision out, every 30 minutes: Elexon → Tiger Data → point-in-time features → LightGBM → optimiser → timing audit.

**01 · Live ingest: Elexon → Tiger Data**
- Six Elexon datasets: prices, wind and demand forecasts, generation mix
- A metadata-driven poller fetches only datasets that changed
- Every row stamped with `available_at`: when Tempo could first have seen it
- Stored in Tiger Data hypertables, rolled up by continuous aggregates

**02 · Point-in-time features, zero leakage**
- Features use only rows with `available_at ≤ decision_time`
- Price lags, rolling spreads, wind and demand forecasts, UK calendar
- Each filter is tagged `-- pit`; a test removes each one and must fail

**03 · Quantile forecast: p10 · p50 · p90**
- Three LightGBM quantile models predict the next 48 half-hourly prices
- The band shows uncertainty, not just a best guess
- Deterministic training: same rows, same model
- Re-run every 30 min on a Vultr box in London

**04 · Cost-gated battery optimiser**
- Greedy pairing: cheapest buy period with the dearest later sell
- LP alternative (cvxpy) over all 48 periods with full battery physics
- Trades only when the spread beats round-trip loss plus wear
- Hold is a decision too: every row logs its reason

**05 · Timing audit: one fork, five replays**
- Click any decision; Tempo replays it 1 h early to 1 h late
- One Tiger zero-copy fork, five timelines on five Vultr workers in parallel
- Shows in pounds what rushing or hesitating would have cost
- The fork is deleted afterwards; only the results are kept

**06 · Walk-forward backtest: 66% of perfect**
- Retrained every week, tested only on weeks it never saw
- £58,711 earned vs £29,265 for a fixed-hours rule: 2× the baseline
- Scored against perfect foresight on the same weeks

### Best Use of Tiger Data

Postgres, built for time. Tiger Data (formerly Timescale) is PostgreSQL in the cloud, extended with TimescaleDB for time-series data.

| Feature | What it is |
|---|---|
| Hypertables | Tables split into chunks by time, so "give me last week" stays fast |
| Continuous aggregates | Summary tables that update themselves as new data arrives |
| Compression | Squeezes old data to about a tenth of its size |
| Forks | A full, writable copy of the whole database, made instantly |

**01 · Tempo's only database**
- `grid_raw`: two years of Elexon market data, plus every new half-hour
- `forecasts` and `decisions`: 48 rows every half hour
- Audit results, replay scratch data and the honesty table

**02 · Hypertables**
- The market data and the decisions log are hypertables
- A query for last week reads only last week's chunk
- Every row records when it became available, so no decision sees the future

**03 · Continuous aggregates**
- Half-hourly, daily and weekly prices, each built on the level below
- They feed the model's features and the dashboard charts
- They update themselves as new prices land

**04 · Compression**
- Two years of data would be about 1.2 GB
- The free tier caps storage at 750 MB
- Compressed, it fits in roughly 120–250 MB

**05 · Forks power the timing audit**
- Click a decision and Tiger forks the live database in about 40 seconds
- Copy-on-write: only the blocks the replays change are copied
- Five replays write into one shared fork, never into live
- The free tier holds only live plus one fork, so our plan of one fork per timeline became one shared fork, identical to the penny
- The fork is deleted afterwards; only the results are kept

### Best Use of Vultr

The compute layer. Tiger supplies the data forks; Vultr supplies the machines that replay against them. Five pre-warmed workers turn one click into five parallel timelines, and a London box keeps Tempo running live.

| Feature | How Tempo uses it |
|---|---|
| Cloud compute | vc2 instances: 1 vCPU workers in New Jersey, a 2 GB backend in London |
| Snapshots | One bootstrapped image, cloned into every worker |
| Instance tags | `tempo-worker` marks the pool; anything untagged is never dispatched to |
| v2 API | Create, list, lease and tear down the fleet from Python |

**01 · Five workers replay in parallel**
- Five `vc2-1c-1gb` instances in `ewr`, beside Tiger's us-east-1
- Pre-warmed all day: a cold boot takes ~40 s to active and ~80 s to SSH, too slow for a click
- One click takes one Tiger zero-copy fork and sends five shifted timelines to five workers at once
- Each worker is a stateless FastAPI app under systemd: `POST /replay` returns the P&L, `GET /health` reports liveness
- A shared bearer token guards `/replay`, so no one can aim a public worker at their own database

**02 · Lease-based scheduling**
- `VultrClient` lists instances tagged `tempo-worker` over the v2 API, following cursor pagination
- Idle means Vultr reports active and no job holds a lease
- `lease()` → `mark_busy()` → `mark_idle()`: one job per worker, always released
- When every worker is busy, jobs queue, so five timelines still finish on three workers
- Without Vultr credentials it falls back to the same worker app in-process, labelled local-1..n

**03 · Snapshot to fleet in one command**
- `build_worker_image.py`: rsync the repo, bootstrap, verify `/health` and the token, snapshot, delete the build box
- `create_workers.py`: clone five workers from the snapshot; idempotent, with `--count`, `--status` and `--delete`
- `create_backend.py`: a separate `lhr` box running the dashboard and the poller, never tagged as a worker
- `time_vultr.py` benchmarks create → active → SSH-ready
- Snapshot ID, SSH key and worker token are written straight into .env

---

## Tech stack

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| Database | Tiger Data (TimescaleDB on PostgreSQL): hypertables, continuous aggregates, compression, zero-copy forks |
| DB access | psycopg 3 |
| Data | pandas, NumPy, pyarrow |
| Forecasting | LightGBM quantile regression, scikit-learn, joblib |
| Optimisation | Greedy pairing (custom), cvxpy linear program |
| Data source | Elexon Insights API (httpx) |
| Compute | Vultr cloud compute (v2 API), Ubuntu 24.04, systemd |
| Worker API | FastAPI + Uvicorn |
| Dashboard | Streamlit |
| Scheduling | APScheduler, systemd units |
| Testing | pytest, respx (HTTP mocks), hypothesis, freezegun, local TimescaleDB in Docker |
| Lint/format | ruff |
| Presentation website | Next.js 15 (static export), React 19, Tailwind CSS 4, Motion, lucide-react |

---

## Architecture and deployment

```
                       Elexon Insights API
                               │
              ┌────────────────▼─────────────────┐
              │ tempo-backend  (Vultr, lhr)      │
              │  tempo-poller    poll.py         │──────┐
              │  tempo-decider   decide.py       │      │ reads / writes
              │  tempo-dashboard Streamlit :8501 │      ▼
              │  tempo-api       uvicorn :8000   │
              │  nginx :80  /  /app/  /api/      │
              └────────────────┬─────────────────┘   Tiger Data free service (us-east-1)
                               │ audit click            primary  ──fork──▶  audit fork
                               ▼                                               ▲
              tempo-worker-1..5 (Vultr, ewr) ── POST /replay (bearer token) ───┘
```

systemd units live in [`deploy/systemd/`](deploy/systemd/): `tempo-dashboard`, `tempo-poller`, `tempo-decider`, `tempo-api` (backend) and `tempo-worker` (workers). [`deploy/bootstrap.sh`](deploy/bootstrap.sh) installs a box as either role; on the backend it also installs nginx with [`deploy/nginx/tempo.conf`](deploy/nginx/tempo.conf), which serves the presentation website at `/`, the pitch dashboard at `/app/` and proxies `/api/` to `tempo-api`. Logs go to `/var/log/tempo/*.log`.

---

## Repo structure

```
tempo/                    the Python package
  config.py               settings from .env: DB URL, battery parameters, Tiger and Vultr credentials
  db/                     schema.sql (hypertables, aggregates, policies), connections, storage stats
  ingest/                 elexon.py (API client), backfill.py, poll.py
  features/               build.py: point-in-time feature builder
  forecast/               lgbm.py (quantile LightGBM), persistence.py (baseline), dataset.py
  optimise/               gate.py (cost gate), greedy.py, lp.py (cvxpy), perfect.py (perfect foresight)
  sim/                    battery.py: battery physics and P&L
  decide/                 engine.py: run_decision(), the live pipeline
  backtest/               walkforward.py, replay.py, metrics.py (honesty table), features.py
  audit/                  orchestrator.py, shifts.py (replay), pool.py (worker pools), selfgrade.py,
                          preflight.py (go/no-go), rehearsal.py, refsim.py
  infra/                  tiger.py (Tiger Cloud REST), vultr.py (Vultr v2 API), deploy.py (ssh/rsync)
  worker/                 main.py: FastAPI replay worker
  dashboard/              app.py (Streamlit), data.py, jobs.py, ui.py, theme.py
scripts/
  dev_db.sh               local TimescaleDB in Docker + schema
  backfill.py             two-year Elexon load
  poll.py                 live poller
  train.py                train the quantile models into models/
  decide.py               live decider, one batch every half hour
  backtest.py             walk-forward backtest
  replay_week.py          pick and export the replay week for the dashboard
  demo_reset.py           go/no-go check before a demo
  build_worker_image.py   build and snapshot the Vultr worker image
  create_workers.py       create, check or delete the worker pool
  create_backend.py       create and deploy the backend box
  time_vultr.py           time instance create → active → SSH
  time_fork.py            time a Tiger fork
  seed_selftest.py        seed a rehearsal decision batch
  export_pitch.py         snapshot the pitch dashboard's data from Tiger into pitch/data/
tests/
  unit/                   no network, no DB
  contracts/              frozen interfaces and schema, point-in-time leak test
  db/                     need the local Docker DB
  live/                   hit real Tiger / Vultr / Elexon (TEMPO_LIVE=1)
  fixtures/               synthetic market and Elexon samples
deploy/                   bootstrap.sh, systemd units, deploy notes
presentation/             the presentation website (Next.js, static export)
pitch/                    the pitch dashboard the presenter drives (Next.js, static export)
docs/                     all project documents
models/                   trained model files (gitignored)
```

---

## Running it locally

```bash
make setup            # venv, deps, .env from template
# edit .env (see below)
make db               # local TimescaleDB in Docker on port 5433 + schema
make test             # unit + contract tests (no network, no DB)
make test-db          # tests that need the local DB
make test-live        # tests that hit real Tiger / Vultr / Elexon (costs money)
make lint
make dashboard        # Streamlit on http://localhost:8501
make api              # JSON API for pitch/ on http://127.0.0.1:8000
```

On Windows, use `.venv/Scripts/python` in place of `.venv/bin/python`, and run `scripts/dev_db.sh` with Git Bash.

### The pipeline by hand

```bash
.venv/bin/python scripts/backfill.py              # two years of Elexon data into TEMPO_DATABASE_URL
.venv/bin/python scripts/poll.py                  # live poller (--once for one cycle)
.venv/bin/python scripts/train.py                 # last 90 days → models/lgbm_p10/p50/p90.joblib
.venv/bin/python scripts/decide.py --once         # one 48-period decision batch now
.venv/bin/python scripts/backtest.py              # walk-forward backtest (synthetic if Tiger is empty)
```

Add `--db local` to the backfill, poll and train scripts to use the Docker DB.

### Configuration (`.env`)

| Variable | What it is |
|---|---|
| `TIGERDATA_PROJECT_ID`, `TIGERDATA_ACCESS_KEY`, `TIGERDATA_SECRET_KEY` | Tiger Cloud REST credentials (forks) |
| `TIGER_PRIMARY_SERVICE_ID` | The live Tiger service the audit forks |
| `TEMPO_DATABASE_URL` | Postgres URL of the live Tiger service |
| `TEMPO_TEST_DATABASE_URL` | Local Docker DB for tests |
| `VULTR_API_KEY`, `VULTR_REGION`, `VULTR_WORKER_PLAN` | Vultr API and worker defaults (`ewr`, `vc2-1c-1gb`) |
| `VULTR_WORKER_SNAPSHOT_ID`, `VULTR_SSHKEY_ID`, `TEMPO_WORKER_TOKEN` | Set by `build_worker_image.py` |
| `BATTERY_CAPACITY_MWH`, `BATTERY_POWER_MW`, `BATTERY_RT_EFFICIENCY`, `BATTERY_CYCLE_COST_GBP` | Battery (2, 1, 0.90, 20) |
| `MID_AVAILABILITY_DELAY_MIN` | Stated delay before a MID price counts as available (10) |
| `TEMPO_AUDIT_FORKS` | `shared` (one fork per audit, default) or `per_shift` (five forks, needs a raised service limit) |
| `TEMPO_LIVE` | `1` to run live tests |

Never commit `.env`.

---

## Deploying to Vultr

```bash
.venv/bin/python scripts/build_worker_image.py    # build box → rsync → bootstrap → /health + token check → snapshot → delete box
.venv/bin/python scripts/create_workers.py        # tempo-worker-1..5 from the snapshot (idempotent)
.venv/bin/python scripts/create_workers.py --status   # list the pool and health
.venv/bin/python scripts/create_workers.py --delete   # destroy every instance tagged tempo-worker
.venv/bin/python scripts/create_backend.py        # create tempo-backend in lhr, deploy repo + .env + models, start units
.venv/bin/python scripts/create_backend.py --deploy   # redeploy code to the existing box
```

`build_worker_image.py` writes the snapshot ID, SSH key ID and worker token into `.env`. `create_backend.py` copies `.env` and `models/lgbm_*.joblib` to the box, and enables `tempo-decider` only once a trained model is present.

---

## Presentation website

A static Next.js 15 site in `presentation/`, with a home page (about, how it works), a Tiger Data page and a Vultr page, all with animated SVG diagrams. Needs Node 20+.

```bash
cd presentation
npm install
npm run dev           # http://localhost:3000, hot reload
npm run build         # static export to presentation/out/
npm start             # serve presentation/out/ locally
```

"Open the app" opens the pitch dashboard, served next to this site at `/app/` on the `tempo-backend` Vultr box (http://136.244.77.120/app/). To point it elsewhere, for example at `http://localhost:3001` when running both sites locally, set `NEXT_PUBLIC_APP_URL` in `presentation/.env.local` before building.

---

## Pitch dashboard

A static Next.js 15 site in `pitch/`: one full-screen page per chapter (Hook, Data, Prediction, Decision, Proof, Timing), driven by the presenter with ← / →. Every number is real: [`scripts/export_pitch.py`](scripts/export_pitch.py) snapshots it from Tiger into `pitch/data/` (read-only). The Live badge and the timing audit call the API (`make api`); the audit can take a real Tiger fork and use the five Vultr workers. What to say is in [docs/demox.md](docs/demox.md); what each chapter shows, and why, is in [pitch/SPEC.md](pitch/SPEC.md).

```bash
.venv/bin/python scripts/export_pitch.py   # refresh pitch/data/ from Tiger
make api                                   # http://127.0.0.1:8000
cd pitch && npm install
npm run dev -- -p 3001                     # http://localhost:3001, hot reload
npm run build && npx serve out -l 3001     # the static site, for presenting
```

On the box it lives at http://136.244.77.120/app/ with the API at `/api/` on the same address. `scripts/create_backend.py --deploy` builds both websites here with npm (the box has no Node), copies the exports to `/var/www/tempo`, and restarts the units; `--no-sites` skips the builds.

---

## Demo day: go/no-go check

Run before every rehearsal and before going on stage. It prints one line per check, then `GO` (exit code 0) or `NO-GO` (exit code 1).

```bash
.venv/bin/python scripts/demo_reset.py              # check, delete stale audit forks, pick a decision to click
.venv/bin/python scripts/demo_reset.py --dry-run    # check only, delete nothing
.venv/bin/python scripts/demo_reset.py --decision N # confirm a specific decision is replayable
.venv/bin/python scripts/demo_reset.py --fork-test  # also take and delete one real Tiger fork and time it (~30-40 s)
.venv/bin/python scripts/demo_reset.py --no-score   # skip the in-process replays used to rank decisions
```

| Check | Fails (NO-GO) when | Warns when |
|---|---|---|
| Tiger | the primary service is missing or not `READY` | the primary is `PAUSED` |
| Stale forks | an `audit-*` fork is left over and can't be deleted (or `--dry-run`) | |
| Service slots | no free slot for the audit's fork (the free tier holds 2 services: the primary plus one fork) | |
| Database | `TEMPO_DATABASE_URL` is unreachable | |
| Prices | `prices_hh` is empty | the newest price is over 3 hours old (poller down?) |
| Decision | no live decision has all 48 periods priced | a shifted timeline beats "as decided" (say so on stage) |
| Workers | any worker fails `/health`, or there is no pool | only local workers (Vultr not configured: don't say "Vultr"), or fewer than 5 |
| Simulator | | workers run a different simulator from this machine (rebuild the worker image) |

It picks the decision to click by replaying recent live decisions in-process. It prefers one where "as decided" beats every shift and a hold sits nearby, and prints the line to say, for example "Charging one period later would have cost £14.30". Those replays write `battery_state` rows under `audit-*` run ids, never under `live`.

Demo-day rules that follow from the Tiger free tier's two-service limit:

- Nobody creates Tiger forks or services on demo day. Any extra service takes the audit's slot.
- Click the timing audit once and wait for it to finish. A second click while the fork exists fails.
- If the fork audit fails on stage, switch the toggle to in-process and say "same replay, run locally".

---

## Challenges and known limits

- **Five forks became one.** We designed one zero-copy fork per timeline. On real Tiger, the third service was refused with `403 ENTITLEMENT_ERROR`: a free project holds two services at once, and paid forks take minutes. Tempo now takes one fork per click, and all five timelines replay inside it under separate run ids. A test shows the fork replay equals the in-process replay to the penny in both layouts. `TEMPO_AUDIT_FORKS=per_shift` brings back five forks on an account with a higher limit.
- **The uncertainty band is overconfident.** The p10–p90 band should hold about 80% of real prices. On 405 settled live forecasts it holds 40%. Trades use p50 only, so the band never changes a decision, and the dashboard says so.
- **Regime breakdown didn't go as expected.** We expected forecasting to matter more in windy weeks. Tempo's lead over persistence is 16 points on calm weeks and 12 on windy ones, and the panel shows it.
- **Price assumption.** Tempo trades at the APX Market Index price for each period. System price publishes about 24 hours late, and N2EX has frequent zero-volume rows.
- **Not built:** parallel walk-forward backtests on the Vultr workers and a battery-size sweep ([docs/time.md](docs/time.md)).

---

## What to improve

The fixes we'd make next, for the limits above.

- **Recalibrate the band.** Conformal adjustment on recent residuals, so p10–p90 really holds about 80% of prices. Then the LP's conservative mode (buy at p90, sell at p10) can use it.
- **Better wind and demand features.** The model should help most in windy weeks and doesn't yet. Actual demand (INDO) and the generation mix (FUELHH) are already stored in Tiger but not used by the model.
- **Room to the ceiling.** Tempo captures 66.4% of perfect foresight (worst week 31.2%). The LP optimiser reaches 68.3% and is one flag away (`scripts/decide.py --optimiser lp`).
- **Reason strings in UK time.** `greedy.py` prints the times inside its reasons in UTC; the pitch site converts them, the API and Streamlit show them as stored.

---

## Docs

| File | What it is |
|---|---|
| [docs/description.md](docs/description.md) | What Tempo is, the three layers, the demo script, why it wins |
| [docs/needs.md](docs/needs.md) | Feasibility findings, every API, key, endpoint and env var |
| [docs/plan.md](docs/plan.md) | Implementation plan, phases, tests, frozen contracts |
| [docs/girik.md](docs/girik.md) | Part A: Data (Elexon → Tiger Data → features) |
| [docs/ernqi.md](docs/ernqi.md) | Part B: Brain (battery, optimiser, forecaster, backtest) |
| [docs/ayo.md](docs/ayo.md) | Part C: Stage (forks, workers, timing audit, dashboard, demo) |
| [docs/a.md](docs/a.md), [docs/b.md](docs/b.md) | Live decisions (Part A) and backtest, replay and clean-up (Part B). Both done |
| [docs/todo_ayo.md](docs/todo_ayo.md), [todo_girik.md](docs/todo_girik.md), [todo_ernqi.md](docs/todo_ernqi.md) | What each of us had left, checked 24–25 Oct |
| [docs/time.md](docs/time.md) | Planned but not built: parallel backtest on the Vultr workers, battery-size sweep |
| [docs/ui-plan.md](docs/ui-plan.md) | UI plan: presentation page and dashboard, tokens, motion spec |
| [docs/ui.md](docs/ui.md) | Dashboard screen content, chart grammar and audit choreography |
| [deploy/README.md](deploy/README.md) | Manual deploy notes |
| [docs/demox.md](docs/demox.md) | Presenter script for the pitch dashboard: what to say at each step of each chapter |
| [pitch/SPEC.md](pitch/SPEC.md) | What each chapter of the pitch dashboard shows, agreed before it was built |
| [info.md](info.md) | Pre-hackathon idea and research. Superseded: don't quote it in the pitch |

---

## Team

| Part | Owner | Scope |
|---|---|---|
| A: Data | Girik | Elexon → Tiger Data hypertables → aggregates → point-in-time features |
| B: Brain | Ernqi | Battery simulator → optimisers → forecaster → walk-forward backtest → honesty metrics |
| C: Stage | Ayo | Tiger forks + Vultr workers → timing audit → dashboard → demo |
