# Tempo, explained part by part

This is a teaching walkthrough of the whole Tempo repository. It starts from "what problem are we solving" and works down to individual functions, in the order data actually flows through the system. Every number in the worked examples was produced by running the real code in this repo, not invented.

How to use it:

- Read Parts 1 to 3 first. They give you the mental model everything else hangs on.
- Parts 4 to 19 each cover one layer of the system. Each one says which files it covers, explains the idea, then goes through the code.
- Part 20 lists things I noticed while reading that are worth knowing (gaps, inconsistencies, honest limits). Read it before you present.
- Part 21 is a quiz with answers. If you can answer those, you understand the project.

---

## Table of contents

1. [The problem in plain English](#part-1-the-problem-in-plain-english)
2. [Vocabulary you need](#part-2-vocabulary-you-need)
3. [The architecture at a glance](#part-3-the-architecture-at-a-glance)
4. [Configuration](#part-4-configuration-tempoconfigpy-envexample)
5. [The database](#part-5-the-database-tempodb)
6. [Getting data in: Elexon ingest](#part-6-getting-data-in-elexon-ingest-tempoingest)
7. [Features and the no-lookahead guarantee](#part-7-features-and-the-no-lookahead-guarantee-tempofeaturesbuildpy)
8. [The battery simulator](#part-8-the-battery-simulator-temposimbatterypy)
9. [The cost gate](#part-9-the-cost-gate-tempooptimisegatepy)
10. [The optimisers](#part-10-the-optimisers-tempooptimise)
11. [Forecasting](#part-11-forecasting-tempoforecast)
12. [The live decision engine](#part-12-the-live-decision-engine-tempodecideenginepy-scriptsdecidepy)
13. [The walk-forward backtest](#part-13-the-walk-forward-backtest-tempobacktest)
14. [The timing audit](#part-14-the-timing-audit-tempoaudit)
15. [Self-grade](#part-15-self-grade-tempoauditselfgradepy)
16. [Pre-demo checks and rehearsal data](#part-16-pre-demo-checks-and-rehearsal-data)
17. [The dashboard](#part-17-the-dashboard-tempodashboard)
18. [Cloud infrastructure and deployment](#part-18-cloud-infrastructure-and-deployment)
19. [The test suite](#part-19-the-test-suite-tests)
20. [Things worth knowing](#part-20-things-worth-knowing-before-you-present)
21. [Check your understanding](#part-21-check-your-understanding)

---

## Part 1: The problem in plain English

### 1.1 The market

Great Britain's wholesale electricity market splits every day into **48 half-hour blocks**, called **settlement periods**. Each block has its own price, in pounds per megawatt-hour (£/MWh).

Prices follow a predictable *shape* but an unpredictable *size*:

- At 3am on a windy night, wind farms make more power than the country needs. Prices fall, sometimes below zero.
- At 6pm on a cold weekday, everyone gets home and turns on heating and ovens. Prices spike.

### 1.2 How a battery makes money

A grid-scale battery buys electricity when it is cheap (charging) and sells it back when it is expensive (discharging). Profit is the price difference, minus what you lose along the way.

It sounds trivial. Three things make it hard:

1. **You have to predict the future.** You commit to charging now based on what you think prices will do over the next 24 hours. Charge at 2am when the real low was 4am and you overpaid.
2. **The battery has physical limits.** It can only hold so much (capacity), charge or discharge so fast (power), and it loses about 10% of energy on every round trip. You cannot "buy every cheap period and sell every expensive one".
3. **Doing nothing is a real decision.** On a flat day, the gap between cheap and expensive may not cover the 10% loss plus wear on the cells. The right call is to **hold**. A system that can't hold loses money on calm days.

### 1.3 What Tempo does about it

Tempo has three layers, which are the whole pitch:

| Layer | What it does | Where in the code |
|---|---|---|
| 1. Live decision engine | Pulls real market data, forecasts the next 24 h of prices as a range, and decides charge / discharge / hold for each of the next 48 periods. Holds when the edge doesn't cover costs, with a written reason. | `tempo/ingest`, `tempo/features`, `tempo/forecast`, `tempo/optimise`, `tempo/decide` |
| 2. Timing audit | Click any past decision. Tempo replays it shifted 1 h earlier, 30 min earlier, as decided, 30 min later and 1 h later, in parallel, on a frozen copy of the database, and shows in pounds what rushing or hesitating would have cost. | `tempo/audit`, `tempo/worker`, `tempo/infra` |
| 3. Honesty | A walk-forward backtest on weeks the model never saw, against honest baselines, reported as a percentage of the best possible result. Plus calibration, regime breakdown and plain "where it's weak" statements. | `tempo/backtest`, `tempo/dashboard` |

The hackathon theme is **TIME** and the track is **HRT: Best Use of Data for Predictions and Decision Making**. Time runs through everything: prices change every half hour, every row records *when it became known*, the battery's job is choosing *when*, and the signature feature asks whether each decision was made at the right *time*.

### 1.4 The one-line pitch

> "It's buy-low-sell-high for a battery. The hard part isn't the price. It's the timing."

### 1.5 The real results (as of 24 Oct 2026)

From backtest run `db-20261024T202144Z` on Tiger, over **100 unseen weeks**:

| Strategy | % of perfect foresight |
|---|---|
| Simple rule (charge 1–5am, sell 5–7pm) | 33.1% |
| Persistence forecast + greedy | 52.9% |
| **Tempo** (LightGBM + greedy), what runs live | **66.4%** |
| Tempo LP (LightGBM + LP optimiser) | 68.3% |
| Perfect foresight | 100% |

Tempo never lost money in a single week (worst week 31.2% of perfect, best 90.2%). The trained model's median forecast error was 24.4 £/MWh against persistence's 33.9 £/MWh on held-out data. Keep these in your head; they come up repeatedly.

---

## Part 2: Vocabulary you need

You can't follow the code without these. Read them once now and come back as needed.

**Settlement period (SP).** One half-hour block. 48 per normal day. Numbered from UK local midnight, so on clock-change days there are **46** (spring forward) or **50** (fall back). This is why the code never computes a time from "date + period number": it always uses the API's UTC `startTime`.

**MW vs MWh.** MW (megawatts) is a *rate*, like speed. MWh (megawatt-hours) is an *amount*, like distance. Running at 1 MW for half an hour moves 0.5 MWh. You'll see `* 0.5` everywhere in the code: it converts a half-hour of MW into MWh.

**The battery's numbers.** 2 MWh capacity, 1 MW power, 90% round-trip efficiency, £20 per full cycle of wear. Starts half full (1 MWh). So from empty it takes 4 periods (2 hours) of full charging to fill.

**State of charge (SoC).** How much energy is in the battery right now, in MWh. Must stay between 0 and capacity.

**Round-trip efficiency.** Put 1 MWh in and you can get 0.9 MWh back out. The code splits that loss evenly: √0.9 ≈ 0.9487 is lost on the way in, and the same on the way out (0.9487 × 0.9487 = 0.9).

**Cycle / degradation cost.** Every time you push a full capacity's worth of energy through the battery, the cells wear a little. Tempo charges £20 per full cycle, counted on energy *sold*.

**Spread.** Sell price minus buy price.

**APX MID.** The price series Tempo uses: Market Index Data from the APX exchange, published by Elexon. Chosen because it's available within the day. (System price arrives ~24 h late; the N2EX index has lots of zero-price rows.)

**Quantile forecast (p10 / p50 / p90).** Instead of one number, the forecaster gives three. p10 is "10% chance the price is below this", p50 is the median, p90 is "90% chance below this". The gap between p10 and p90 should contain **80%** of real prices if the forecast is honest.

**Lookahead / leakage.** Using information at decision time that wasn't actually available yet. The cardinal sin of backtesting. It makes results look great and is a lie. Tempo's data layer is built around preventing it.

**available_at.** Every data row stores *when it became known*, separate from *what period it describes* (`start_time`). A forecast published at 7pm for tomorrow's 6pm has `start_time` = tomorrow 6pm and `available_at` = today 7pm.

**Point-in-time (PIT).** "Using only what was available at that moment." Every feature for a decision at time T must come from rows with `available_at <= T`.

**Perfect foresight.** The best possible profit if you knew actual prices in advance. The ceiling. Used to normalise results ("% of perfect").

**Walk-forward backtest.** Train on a window of past weeks, test on the following week the model never saw, slide forward, repeat. The honest way to test a forecasting system.

**Hypertable** (TimescaleDB / Tiger Data). A Postgres table automatically split into time-based chunks. Fast for "give me this time range" queries on big time series.

**Continuous aggregate (cagg).** A materialised summary view (e.g. half-hourly → daily → weekly averages) that TimescaleDB keeps up to date automatically as new rows arrive.

**Tiger Data / Tiger Cloud.** The hosted TimescaleDB service Tempo's database runs on. A "service" is one database instance.

**Fork (zero-copy fork).** A new, writable database service that starts as an exact copy of another one at a moment in time, without physically copying the data (copy-on-write). On Tiger's free tier it's ready in about 36–42 seconds.

**Vultr.** The cloud provider running Tempo's servers: five small "worker" boxes that do replays, and a "backend" box running the dashboard, poller and decision engine.

**Run id.** A text label on rows in `decisions`, `forecasts` and `battery_state` that says which "timeline" they belong to. `live` is the real system. `audit-123-+1` is a replay. `selftest` is rehearsal data. Keeping these separate is how replays never pollute the live record.

---

## Part 3: The architecture at a glance

### 3.1 The data flow

```
Elexon BMRS API  (prices, wind forecast, demand forecast, demand outturn, fuel mix, system price)
      │  backfill: 2 years of history          poller: every 60 s, last 2 days
      ▼
grid_raw hypertable on Tiger   (every row: start_time + available_at)
      │
continuous aggregates: prices_hh → prices_daily → prices_weekly
      │
build_features(decision_time)   ← only rows available at decision_time
      │
LightGBM quantile forecaster    → p10 / p50 / p90 for the next 48 periods
      │
Greedy optimiser + cost gate    → charge / discharge / hold, with a reason, per period
      │
forecasts + decisions tables    (48 rows per batch, run_id 'live', every half hour)
      │
      ├──────────────────────────────┬─────────────────────────────┐
      ▼                              ▼                             ▼
Dashboard (Streamlit)          Timing audit                  Walk-forward backtest
live view, honesty panel       click → 1 Tiger fork →        (offline, scripts/backtest.py)
                               5 Vultr workers replay        → backtest_results table
                               shifts −2..+2 in parallel
                               → audits table
```

### 3.2 The repository layout

```
tempo/                  the Python package
  config.py             settings from .env
  db/                   schema.sql, connection helpers, storage stats
  ingest/               Elexon client, backfill, live poller
  features/             build_features: the point-in-time feature builder
  sim/                  battery physics (simulate)
  optimise/             cost gate, greedy, LP, perfect foresight
  forecast/             persistence, LightGBM, training-set builder (nn.py is an empty stub)
  decide/               run_decision: the live pipeline
  backtest/             walk-forward, in-memory features, metrics, replay week
  audit/                shift replay, orchestrator, worker pool, self-grade, preflight, rehearsal
  worker/               FastAPI app that runs on each Vultr worker
  infra/                Tiger and Vultr REST clients, deploy helpers
  dashboard/            Streamlit app, data sources, charts, theme
scripts/                command-line entry points (backfill, poll, train, decide, backtest, demo_reset, …)
deploy/                 bootstrap.sh and systemd units for the Vultr boxes
tests/                  unit/  contracts/  db/  live/  fixtures/
models/                 trained model files (joblib gitignored), training.json, replay_week.parquet
docs/                   design docs, plans, per-person todo lists
```

### 3.3 Who owned what

The team split the build into three parts, and file docstrings say "Owner: …":

- **Girik, Part A "Data":** Elexon → Tiger → features. `ingest/`, `db/`, `features/`.
- **Ernqi, Part B "Brain":** battery, optimisers, forecaster, backtest. `sim/`, `optimise/`, `forecast/`, `backtest/`, `selfgrade.py`.
- **Ayo, Part C "Stage":** forks, workers, timing audit, dashboard, demo. `audit/`, `worker/`, `infra/`, `dashboard/`, `deploy/`, most `scripts/`. Ayo also wrote `decide/engine.py` and `forecast/dataset.py` on Ernqi's behalf.

The interfaces between the parts (table shapes, function signatures) were "frozen at Gate 0" in `docs/plan.md`, so each person could build against the contract before the others finished. You'll see this pattern a lot: `refsim.py` is a stand-in battery simulator Ayo wrote so the audit could be built before Ernqi's real one existed.

### 3.4 The lifecycle of one decision, end to end

Follow one batch through the system. This is the single most useful thing to understand.

1. **12:00:00 UTC.** Elexon publishes the price for the 11:30–12:00 period. Within 60 s the poller sees `/datasets/metadata/latest` move, fetches the last 2 days of MID, normalises it and upserts it into `grid_raw`. The row gets `available_at = 11:30 + 30 min + 10 min = 12:10`.
2. **12:01.** `scripts/decide.py` wakes (it runs one minute past every half hour) and calls `run_decision(conn, now=12:01)`.
3. `build_features(conn, 12:01)` asks the database for everything known at 12:01. The newest usable price is the 11:00 bucket (a bucket is usable once its start is at least 40 min before the decision, and 12:01 − 40 min = 11:21). The 11:30 price arrived at 12:00 but counts as available only from 12:10, so it's ignored. It also fetches yesterday's and last week's prices for each target, the last complete day's spread, last complete week's mean and stddev, and the latest wind and demand forecasts published at or before 12:01. It returns a 48-row table, one row per target period 12:30, 13:00, … 12:00 tomorrow.
4. The LightGBM forecaster turns that into p10/p50/p90 for each of the 48 targets.
5. The greedy optimiser plans the battery against p50: which periods to charge, which to sell, which to hold, each with a reason.
6. `write_batch` inserts 48 `forecasts` rows and 48 `decisions` rows, all sharing `decided_at = 12:01` and `run_id = 'live'`.
7. **A day later**, all 48 periods have real prices. The batch is now "settled" and shows up in the dashboard's timing audit picker.
8. **On stage**, you click one decision from that batch. Tempo forks the database, five workers each replay the batch shifted by −2, −1, 0, +1, +2 periods against actual prices, and writes five `audits` rows. The dashboard shows "Charging 30 minutes later would have cost £X."

---

## Part 4: Configuration (`tempo/config.py`, `.env.example`)

### 4.1 What it is for

One place that reads settings from the environment (or a `.env` file) so nothing else hard-codes credentials or battery numbers.

### 4.2 How it works

- On import, it calls `load_dotenv(REPO_ROOT / ".env", override=False)`. `override=False` means real environment variables win over `.env`, which matters on the servers (systemd sets them) and in tests.
- `env(name, default)` treats empty strings as unset, so a blank `VULTR_API_KEY=` line in `.env` counts as "not configured".
- `require(name)` raises a helpful error pointing at the docs if something mandatory is missing.
- Settings are grouped into frozen dataclasses:
  - `BatteryParams`: capacity 2 MWh, power 1 MW, efficiency 0.90, cycle cost £20.
  - `TigerSettings`: project id, access/secret keys, the primary service id. `.configured` is true only when all three credentials exist.
  - `VultrSettings`: API key, region `ewr` (New Jersey, next to Tiger's us-east-1), plan `vc2-1c-1gb`, snapshot id, SSH key id.
  - `Settings`: database URLs, Elexon base URL, `PRICE_PROVIDER=APXMIDP`, `MID_AVAILABILITY_DELAY_MIN=10`, `TEMPO_LIVE` (whether to run tests that hit real clouds), and `TEMPO_AUDIT_FORKS` (`shared` or `per_shift`, explained in Part 14).
- `settings()` is wrapped in `@lru_cache(maxsize=1)`, so the environment is read once per process. Tests that change the environment call `settings.cache_clear()`.

Importing this module never touches the network and never fails. Missing values are just `None`.

### 4.3 The `.env` variables worth knowing

| Variable | Meaning |
|---|---|
| `TEMPO_DATABASE_URL` | The Tiger primary database. Everything live reads and writes here. |
| `TEMPO_TEST_DATABASE_URL` | Local Docker TimescaleDB on port 5433, for `tests/db`. |
| `TIGERDATA_*`, `TIGER_PRIMARY_SERVICE_ID` | Credentials for Tiger's REST API (needed to create and delete forks). |
| `VULTR_API_KEY`, `VULTR_WORKER_SNAPSHOT_ID`, `VULTR_SSHKEY_ID` | Vultr API access and the worker image. |
| `TEMPO_WORKER_TOKEN` | Shared secret: the laptop/backend sends it to workers, workers reject requests without it. |
| `MID_AVAILABILITY_DELAY_MIN=10` | How long after a period ends we assume its MID price is known. Critical for no-lookahead. |
| `TEMPO_AUDIT_FORKS=shared` | One fork per audit click (fits the free tier). |

---

## Part 5: The database (`tempo/db/`)

### 5.1 `schema.sql`, table by table

All timestamps are UTC. Every hypertable is partitioned on its first column.

#### `grid_raw`: all raw market data, in "long" format

```
start_time | available_at | dataset | series | value | settlement_date | settlement_period
```

"Long format" means one row per (period, publication, dataset, series) instead of one wide row per period with lots of columns. A new dataset just adds rows, never columns.

- `dataset` is one of `MID`, `WINDFOR`, `NDF`, `INDO`, `FUELHH`, `DISEBSP` (explained in Part 6).
- `series` distinguishes sub-series: for MID it's the data provider (`APXMIDP`) or `APXMIDP:volume`; for FUELHH it's the fuel type; for NDF it's the boundary (`N` = national).
- The **primary key** is `(start_time, available_at, dataset, series)`. Including `available_at` is the key design choice: the *same* target period can have *many* rows, one per publication. A wind forecast for tomorrow 6pm published at 9am and re-published at 3pm are two separate rows. That's what lets the system ask "what did we know at 1pm?" and get the 9am version.
- Two indexes: by `(dataset, series, start_time DESC)` for "latest prices" queries and by `available_at DESC`.

#### The three continuous aggregates

```
prices_hh     = half-hourly: avg price, sum volume, from MID/APXMIDP rows
prices_daily  = per UK day (Europe/London): mean, min, max, spread = max − min, n, sum_price, sum_sq
prices_weekly = per UK week: mean, stddev, average daily spread
```

These are **hierarchical**: `prices_daily` is built from `prices_hh`, and `prices_weekly` from `prices_daily`. Points worth understanding:

- Daily and weekly buckets use `'Europe/London'`, so a "day" is a UK settlement day (46 or 50 periods on clock-change days), not a UTC day.
- **Why `n`, `sum_price`, `sum_sq` in daily?** You can't compute an exact weekly standard deviation by averaging daily standard deviations. But you can from the raw sums: variance = (Σx² − (Σx)²/n) / (n − 1). Storing those sums in the daily view lets the weekly view compute the exact stddev over all half-hours in the week. That's the formula you see in `prices_weekly`.
- `materialized_only = false` turns on **real-time aggregation**: queries combine the stored (materialised) part with a live computation over rows newer than the last refresh. So the dashboard's chart includes a price that arrived 30 seconds ago.
- `WITH NO DATA` means the views start empty and the refresh policies fill them. (It also lets the file run inside a transaction on Tiger.)
- **Refresh policies**: `prices_hh` refreshes every 5 minutes over the last 3 days, daily every 30 minutes, weekly every hour.
- The aggregates are keyed on `start_time` only and **carry no `available_at`**. That's a problem for point-in-time correctness, solved by a rule in `build_features` (Part 7, "Option A").

#### Compression

```sql
ALTER TABLE grid_raw SET (timescaledb.compress, compress_segmentby = 'dataset, series',
                          compress_orderby = 'start_time, available_at');
SELECT add_compression_policy('grid_raw', INTERVAL '7 days');
```

Two years of uncompressed data was estimated at ~1.2 GB; the Tiger free service caps storage at 750 MB and goes **read-only** at the cap. Columnar compression gets it to roughly 120–250 MB. `segmentby dataset, series` stores each series as its own compressed run, which compresses well (similar values next to each other) and means loading a new dataset doesn't rewrite existing segments. Chunks older than 7 days compress automatically.

#### `ingest_log`: backfill bookkeeping

One row per fetched window: `(dataset, window_start, window_end, rows, fetched_at)`. The backfill uses this, and only this, to decide what's already loaded. The comment explains why: the first two-year run inferred coverage from "are there any rows in this window?", and because Elexon returns whole settlement days, each 60-day response spilled a few hours into the next window, so the next window looked "already loaded" and was skipped. MID, INDO and FUELHH silently loaded 7 of 13 windows. The log fixes that by recording exactly what was fetched.

#### `forecasts` and `decisions`

```
forecasts: forecast_id, decided_at, target_time, p10, p50, p90, model, run_id
decisions: decision_id, decided_at, target_time, action, mw, reason, expected_spread, forecast_id, run_id
```

- One **batch** = 48 rows sharing one `decided_at` and `run_id`.
- `action` is constrained to `charge`, `discharge`, `hold` by a `CHECK`.
- `mw` is signed: positive charges, negative discharges, zero holds.
- Each decision points at its forecast row via `forecast_id`.
- Index `(run_id, target_time)` supports "decisions for this run around this time" queries.

#### `battery_state`

```
ts, soc_mwh, cum_pnl_gbp, run_id     PRIMARY KEY (ts, run_id)
```

The state of charge and cumulative profit at the **end** of each period, per run. Replays write here under their own run id (`audit-…`, `selfgrade-…`).

#### `audits`

One row per shift of a timing audit: `decision_id, shift (−2..2), pnl_gbp, pnl_delta_gbp, mode ('inprocess' or 'fork'), fork_service_id, worker_id, started_at, finished_at`.

#### `backtest_results`

One row per (run_id, week_start, strategy): `pnl_gbp, perfect_pnl_gbp, pct_of_perfect, regime`. The honesty panel reads the latest run.

### 5.2 `conn.py`: connection and write helpers

- `get_conn(url=None, autocommit=True)`: opens a psycopg 3 connection to `TEMPO_DATABASE_URL`. Autocommit by default, because some TimescaleDB commands (refreshing aggregates, VACUUM) refuse to run inside a transaction.
- `run_sql(conn, query, params)`: execute and return rows (or `[]`).
- `split_statements` / `apply_schema`: applies `schema.sql` one statement at a time, like `psql -f`. It strips `--` comments first so a `;` inside a comment doesn't split a statement. Deliberately simple: it refuses files containing `$$` function bodies. Runnable as `python -m tempo.db.conn apply` (written because Windows had no `psql`).
- `grid_raw_rows(df)`: validates a DataFrame before insert. It **rejects naive timestamps** rather than assuming UTC, with the comment: "a silent 1-hour BST shift would leak the future". It also rejects NaN values.
- `upsert_grid_raw(conn, df)`: the insert used by both backfill and poller. Trick: `COPY` is ~10× faster than row-by-row inserts but can't skip duplicates. So it `COPY`s into a temporary staging table, then does `INSERT … SELECT … ON CONFLICT DO NOTHING` into `grid_raw`. You get speed *and* idempotency (re-running the same load inserts nothing new).
- `refresh_caggs(conn, start, end)`: refreshes the three aggregates over a range, parents first.

### 5.3 `stats.py`: storage

- `storage_mb(conn)`: `pg_database_size` in MiB.
- `tiger_storage_mb()`: Tiger's own `metrics.storage_mb` from its REST API. This is the number Tiger actually enforces the 750 MB cap on, and it includes ~340 MB of overhead Postgres can't see. The backfill guard uses this one against Tiger.
- `compress_chunks(conn)`: compresses any chunk older than 7 days that isn't compressed yet or has new uncompressed rows (`status & 1` = compressed, `status & 8` = partial). Then it `REINDEX`es each chunk (compression leaves ~3 MB of stale index pages per chunk) and `VACUUM`s (recompression leaves dead tuples: 193 MiB right after a load vs 62 MB after vacuum). All so the storage cap sees the real size.
- `storage_stats(conn)`: rows, bytes before/after compression, ratio. Feeds the dashboard's "X rows, compressed Y%" line.

---

## Part 6: Getting data in: Elexon ingest (`tempo/ingest/`)

### 6.1 The six datasets

Elexon's Insights API is free and needs no key. Tempo pulls:

| Dataset | What it is | `available_at` comes from | Role |
|---|---|---|---|
| `MID` | Market Index price + volume, per period | **derived**: `start_time + 30 min + 10 min` | The price Tempo trades on and forecasts |
| `WINDFOR` | Wind generation forecast, hourly | `publishTime` | Feature (forecast) |
| `NDF` | National demand forecast | `publishTime` | Feature (forecast) |
| `INDO` | Initial national demand outturn (actual) | `publishTime` | Stored, not used in features yet |
| `FUELHH` | Generation by fuel type, half-hourly | `publishTime` | Stored for context |
| `DISEBSP` | System sell price | `createdDateTime` | Stored; too late (~24 h) for live decisions |

### 6.2 `elexon.py`: the client and normalisation

**The `DatasetSpec` registry.** Each dataset records its history ("bulk", stream) endpoint, its live endpoint (capped at 7 days), and how its time window is expressed in the URL:

- `from_to`: MID uses `from`/`to`.
- `publish`: forecasts and FUELHH use `publishDateTimeFrom/To`, i.e. you select by *when it was published*.
- `settlement_date`: INDO uses settlement dates.
- `per_day`: DISEBSP has one URL per date.

`window_params` turns a `[start, end)` into the right query parameters. `chunk_range(start, end, days)` yields back-to-back windows of at most `days` days.

**`ElexonClient.get`** retries on 429 (rate limit) and 5xx errors with exponential backoff (1 s, 2 s, 4 s, …), honours a `Retry-After` header, and gives up after 5 attempts. `sleep` is injectable so tests don't actually wait. `fetch_window` hides the per-day DISEBSP endpoint behind the same interface as the others.

**`normalise(dataset, rows)`** converts raw API JSON into `grid_raw` format. This is where the point-in-time guarantee starts. The rules (from the module docstring):

1. `start_time` is always the API's `startTime` in UTC. Never computed from settlement date + period, which breaks on 46/50-period days.
2. `available_at` is the API's publish time when there is one. MID has none, so it's **derived**: period start + 30 min (the period's end) + `MID_AVAILABILITY_DELAY_MIN` (10). This is conservative: Elexon was seen publishing the 18:30 period at 18:42, so we assume 18:40, and the build_features rules ignore the row until then. The assumption is stated on the dashboard.
3. MID rows with `volume == 0` are dropped (they carry a fake 0.0 price).
4. `_utc` refuses timestamps without a timezone: if the API ever changed shape, guessing would risk a silent leak.
5. MID is split into two rows per period: the price (series `APXMIDP`) and the volume (series `APXMIDP:volume`).

### 6.3 `backfill.py`: two years of history, resumable

`backfill(conn, client, days=730)` loads every dataset over `[end − 730 days, end)`, where `end` defaults to today's midnight UTC (today's partial day is the poller's job).

The order is deliberate: `MID, DISEBSP, INDO, WINDFOR, FUELHH, NDF`. Small and essential first; NDF is ~60% of all rows and loaded last, because it's the one you'd trim if storage ran out.

`load_dataset` goes window by window (60 days by default):

1. If `ingest_log` says this exact window was loaded, skip it (resume).
2. If storage is above `max_storage_mb`, raise `StorageLimitExceeded` *before* fetching, so the Tiger service never hits its read-only cap. The message tells you resume will pick up here.
3. Fetch, normalise, then **in one transaction** upsert the rows and write the `ingest_log` row. Either both commit or neither, so the log never claims a window that didn't land.
4. Compress chunks after every window. (Originally it compressed at the end of each dataset, and nine NDF windows, ~1.4 M rows, piled up uncompressed on the 750 MB service.)

After each dataset, `coverage()` checks the loaded data actually spans the range, day by day, and reports gaps ("starts late", "ends early", "gap: no data between X and Y"). A half-load raises no error anywhere else, so this is the only alarm.

`lookahead_check(conn)` counts rows that claim something impossible: a publish time in the future for INDO/FUELHH/DISEBSP/WINDFOR/NDF, or a MID price for a period that hasn't started. Must be 0.

### 6.4 `poll.py`: the live poller

`Poller.poll_once()`:

1. Calls `/datasets/metadata/latest`, which lists each dataset's `lastUpdated` timestamp.
2. For each dataset whose `lastUpdated` changed since last time, fetches the last 2 days from the live endpoint (NDF in 1-day windows, because its live endpoint rejects longer ones), normalises, and upserts through the same functions as the backfill. Same stamping rules, same idempotency.
3. Only remembers the new `lastUpdated` *after* a successful upsert, so a failed fetch is retried next cycle.

`run()` loops every 60 s forever. Every exception is logged and swallowed; one bad response never kills the loop. The 2-day lookback on the first cycle also closes any gap since the backfill.

---

## Part 7: Features and the no-lookahead guarantee (`tempo/features/build.py`)

This is the most important file for the honesty story. Every number Tempo reports rests on it.

### 7.1 The signature

```python
build_features(conn, decision_time, horizon=48) -> DataFrame
```

Returns 48 rows, one per target period (the next 48 half-hours after `decision_time` floored to the half hour), with 16 float columns and **no NaN anywhere**.

### 7.2 The 16 feature columns

| Column | Meaning |
|---|---|
| `price_lag_1d` | Price at the same time exactly 24 h before the target |
| `price_lag_7d` | Price exactly 168 h (one week) before the target |
| `price_last_known` | The most recent price available at decision time |
| `hours_since_last_price` | How stale that price is |
| `daily_spread_lag_1d` | Max − min price on the UK day before the target's day (or the latest complete day) |
| `weekly_mean`, `weekly_std` | Mean and stddev of the latest complete UK week: the "regime" |
| `wind_fc` | Latest wind forecast for the target published at or before decision time |
| `demand_fc` | Latest national demand forecast, same rule |
| `wind_share_fc` | `wind_fc / demand_fc`: how much of demand wind will cover. High = cheap |
| `hour`, `dow`, `is_weekend`, `period_of_day` | Calendar, in **UK local time** because people's behaviour follows the local clock |
| `lag_missing` | 1 if any price-based value had to fall back |
| `fc_missing` | 1 if a forecast value had to be filled |

These cover the three timescales in the pitch: half-hourly (lags, forecasts, calendar), daily (spread), weekly (regime).

### 7.3 The point-in-time rules, two different mechanisms

**Forecasts (WINDFOR, NDF) read `grid_raw` directly**, which has `available_at`:

```sql
SELECT DISTINCT ON (start_time) start_time, value FROM grid_raw
WHERE dataset = 'WINDFOR' AND start_time BETWEEN … 
  AND available_at <= %(T)s  -- pit
ORDER BY start_time, available_at DESC
```

`DISTINCT ON (start_time) … ORDER BY available_at DESC` = "for each target hour, the newest publication that existed at T". A forecast published one minute after the decision is invisible.

**Prices read the aggregates**, which have no `available_at`. So they use what the code calls **"Option A"**: since every MID row's `available_at` is exactly `start + 40 min` (stamped at ingest), a half-hour bucket is usable iff `bucket_start <= T − 40 min`. That's the `cutoff`:

```python
cutoff = T - timedelta(minutes=30 + delay)  # latest usable bucket start
complete_by = cutoff + HALF_HOUR  # a day/week is usable once it ends by here
```

A day or week is only usable once **all** its half-hours are usable, which is why daily and weekly queries check that the bucket's *end* is `<= complete_by`. The aggregate for a day that's still in progress is computed from whatever half-hours exist in the table, which can include ones that weren't "available" yet at T. Waiting for the whole day or week to be usable avoids that, and also avoids a half-day spread or a half-week stddev that would mean something different from the complete ones the model was trained on.

**The guard that makes Option A safe.** Option A is only correct if MID was actually loaded with the same delay as the current config. If someone lowered `MID_AVAILABILITY_DELAY_MIN` to 0 without reloading, Option A would start using prices 10 minutes before they were known. So `_check_mid_offset` first queries the actual `available_at − start_time` of recent MID rows, and if it isn't exactly `30 + delay` minutes, raises `PointInTimeError`. Quote from the docstring: "A leak cannot hide behind an edited constant."

**Every point-in-time filter is one SQL line ending in `-- pit`.** The test `tests/db/test_pit_leak.py` was used to delete each `-- pit` line in turn, and the leak test must fail every time. This is a **mutation test**: it proves each filter is actually doing work, not just present.

### 7.4 Execution details

- All six queries go to the database in **one round trip** using `conn.pipeline()`. Tiger is in us-east-1 and the decision runs from London, so six sequential round trips would be slow.
- If no price exists in the 8 days before T, it raises `ValueError` (nothing sensible to forecast from).

### 7.5 The fallback rules (why there's never a NaN)

Missing values never become NaN (LightGBM could handle NaN, but silent NaN hides problems):

- Missing lags (e.g. last week's price is absent) fall back to `price_last_known` and set `lag_missing = 1`.
- Missing daily spread or weekly stddev fall back to 0 with `lag_missing = 1`.
- Forecasts: WINDFOR is hourly, so 10:30 uses the 10:00 value (**forward-fill**). It doesn't interpolate between 10:00 and 11:00, because the 11:00 forecast might not have been published yet: interpolating would leak. Gaps are forward-filled from the latest earlier hour, then back-filled from later targets of the same decision (all of which were published by T, so neither direction leaks), with `fc_missing = 1`.

---

## Part 8: The battery simulator (`tempo/sim/battery.py`)

### 8.1 The contract

```python
simulate(battery, schedule_mw, prices) -> SimResult(pnl_gbp, gross_pnl_gbp, cycle_cost_gbp,
                                                    soc_path, cycles, clipped_mwh)
```

`schedule_mw[k] > 0` charges in period k, `< 0` discharges. Every optimiser, the backtest, the replay and the audit all score schedules with this one function, so they all agree on physics.

### 8.2 The energy accounting, per period

Let e = |mw| × 0.5 (MWh at the grid side) and s = √0.9 ≈ 0.9487:

- **Charge**: buy e from the grid, SoC rises by e × s. Cost = e × price.
- **Discharge**: SoC falls by e / s, sell e to the grid. Revenue = e × price.
- **Clipping**: if a period would overfill or overdrain, only the part that fits is traded. The rest is `clipped_mwh` and is never bought or sold (you don't pay for energy you couldn't store).
- **Cycles** = MWh sold / capacity. **Cycle cost** = cycles × £20.
- **pnl_gbp** = gross trading profit − cycle cost.

### 8.3 Worked example 1: a clean cycle

Battery starts at 1 MWh. Charge 1 MW for two periods at £30, then discharge 1 MW for two periods at £100.

```
period   mw    price   SoC after
  0     +1      30     1.474   (bought 0.5 MWh, stored 0.5 × 0.9487 = 0.474)
  1     +1      30     1.949
  2     −1     100     1.422   (sold 0.5 MWh, drew 0.5 / 0.9487 = 0.527)
  3     −1     100     0.895
```

Bought 1.0 MWh for £30. Sold 1.0 MWh for £100. Gross = £70. Sold 1.0 MWh = 0.5 cycles × £20 = £10 wear. **pnl = £60.** Notice the battery ends at 0.895, lower than it started: the 10% loss came out of the energy that was already in there.

### 8.4 Worked example 2: clipping

Same battery, charge 1 MW for four periods at £30:

```
SoC after: 1.474, 1.949, 2.000, 2.000      clipped = 0.946 MWh
```

The third period could only store 0.051 MWh before hitting 2.0; the fourth stored nothing. Only the energy that fit was paid for (gross = −£31.62). This is exactly what happens to the "simple rule" baseline: it blindly charges for 8 periods from 1am to 5am, but the battery fills after about 4.

---

## Part 9: The cost gate (`tempo/optimise/gate.py`)

### 9.1 The question it answers

"Is buying at price B and selling at price S worth a cycle?"

### 9.2 The derivation

Per 1 MWh bought: you pay B. You get √0.9 × √0.9 = 0.9 MWh back to sell, earning 0.9 × S. Wear is charged per MWh sold: 0.9 × (20 / 2) = £9. So profit = 0.9S − B − 9. Rearranged:

```
S − B   >   (1 − 0.9) × S   +   0.9 × 20 / 2
spread      efficiency loss     degradation (£9/MWh)
```

`cost_gate(buy, sell, battery)` returns `(ok, spread, reason)`, where the reason is a human sentence. The docstring notes `ernqi.md` originally wrote the degradation as £10 (full cycle cost per MWh); charging it on the 0.9 MWh actually sold (£9) makes "the gate says ok" *identical* to "simulate() shows a profit". The gate and the simulator can never disagree.

### 9.3 Worked examples (real output)

| Buy | Sell | Spread | Cost | Result |
|---|---|---|---|---|
| 40 | 100 | 60 | 10.00 + 9.00 = 19.00 | **trade**: `spread 60.00 > cost 19.00 (efficiency loss 10.00 at 10% + degradation 9.00/MWh)` |
| 50 | 65 | 15 | 6.50 + 9.00 = 15.50 | **hold**: `spread 15.00 <= cost 15.50 …` |
| 60 | 75 | 15 | 7.50 + 9.00 = 16.50 | **hold** |

Same £15 spread, but at higher price levels the 10% efficiency loss costs more, so it fails by more. The rule of thumb: on a typical day you need a spread of roughly £15–20/MWh before cycling is worth it.

`TOLERANCE_GBP = 1e-9`: a spread exactly at the threshold counts as not worth it.

---

## Part 10: The optimisers (`tempo/optimise/`)

All optimisers share one interface:

```python
optimiser.plan(quantiles: DataFrame[p10, p50, p90], battery) -> DataFrame[action, mw, expected_spread, reason]
```

indexed by target time. Every row gets a reason, trades included.

### 10.1 Greedy (`greedy.py`), what runs live

**Idea:** repeatedly find the single best (buy period, later sell period) pair and move as much energy between them as the battery allows. Stop when no pair passes the cost gate or no energy can move.

Step by step:

1. Uses **p50 only**. Works in MWh *stored in* the battery.
2. Each period has `charge_room` (up to 1 MW × 0.5 × √0.9 MWh stored) and `discharge_room` (1 MW × 0.5 / √0.9 MWh drawn). A period can be used for charging or discharging, never both.
3. The energy already in the battery at the start is a free source called `STOCK` (pseudo period −1). It was paid for earlier, so selling it only needs to beat wear (price > £10/MWh).
4. Loop: for every sell period j and every earlier buy i, compute value per MWh = 0.9 × p[j] − p[i] − 9. Take the best pair that passes `cost_gate`, and move `amount` = min(charge room at i, discharge room at j, space left in the battery between i and j). For STOCK, the amount is limited by the lowest SoC from j onward (SoC must stay ≥ 0).
5. Update `soc_after`, the rooms, and remember which pair each period first joined (for the reason text).
6. Convert stored/drawn MWh back to MW.
7. Write reasons: trades say "charge for sale at 03:00: spread 30.00 > cost 15.00…" or "sell energy bought at 01:00…" or "sell stored energy: price 90.00 > wear 10.00/MWh". Holds look for the best pair the period *could* have joined and explain why not: the gate failed, the battery was full in between, or "better-paying periods already use the battery".

**Worked example (real output).** Eight periods from 00:00, p50 = `[50, 30, 25, 40, 90, 110, 60, 55]`, battery starting at 1 MWh:

```
00:00  hold        hold: battery full between 00:00 and 02:30 (SoC 2.00 of 2.00 MWh)
00:30  charge 1.00 charge for sale at 03:00: spread 30.00 > cost 15.00 …
01:00  charge 1.00 charge for sale at 02:00: spread 65.00 > cost 18.00 …
01:30  charge 0.11 charge for sale at 03:30: spread 15.00 > cost 14.50 …
02:00  sell   1.00 sell stored energy: price 90.00 > wear 10.00/MWh
02:30  sell   1.00 sell stored energy: price 110.00 > wear 10.00/MWh
03:00  sell   1.00 sell energy bought at 01:00: spread 35.00 > cost 15.00 …
03:30  sell   0.79 sell energy bought at 00:30: spread 25.00 > cost 14.50 …
```

Profit: £103.22. Perfect foresight on the same prices also gets £103.22, because greedy was handed the true prices here. In real use greedy gets the *forecast*, and that's where profit is lost. Note 00:00 holds even though £50 → £110 passes the gate: the battery would be full before the peak, so there's no room.

**Flat day, battery empty**, p50 = `[50, 52, 51, 53, 52, 50, 51, 52]`: every period holds, each with a reason like `hold: spread 3.00 <= cost 14.30 (efficiency loss 5.30 at 10% + degradation 9.00/MWh)`. This is the "doing nothing is a decision" story in code. (With the default half-full battery, it would still sell the free starting energy, because £52 beats the £10 wear.)

### 10.2 Perfect foresight (`perfect.py`), the ceiling

A **linear program** solved with `cvxpy` and the HiGHS solver, on actual prices:

```
variables:  c[k] ≥ 0 (charge MW), d[k] ≥ 0 (discharge MW), soc[0..n]
soc[0] = starting SoC
soc[k+1] = soc[k] + 0.5 × (c[k] × √eff − d[k] / √eff)       (same physics as simulate)
0 ≤ soc ≤ capacity,   c ≤ power,   d ≤ power
maximise   0.5 × (price · d − price · c)  −  0.5 × wear × Σd
```

End SoC is free. One subtlety: an LP can choose to charge *and* discharge in the same period. That only pays at very negative prices (it burns energy through the 10% loss to get paid for consumption), but `simulate()` only accepts one net number per period. So if it happens, the problem is re-solved as a **MILP** (mixed-integer): a boolean `charging[k]` forces each period to be either charge or discharge, never both.

Because it knows actual prices and respects every constraint, nothing can beat it. `tests/unit/test_perfect_is_upper_bound.py` checks this with **Hypothesis** (random price arrays from −150 to 400 £/MWh): greedy, the simple rule, and random schedules never beat it.

### 10.3 LP optimiser (`lp.py`), the backtest row

The *same* LP as perfect foresight, but run on the **p50 forecast** instead of actual prices. Then:

- `_executable(mw)` cleans the schedule: zero any flow under 1 kW (solver noise), then trim each period to what the battery can actually do, and repeat until nothing changes. Zeroing a tiny early sale leaves extra energy in the battery, which can make a later "charge to exactly full" overfill, which trimming fixes, which can create another tiny flow... hence the loop.
- Reasons: groups the schedule into cycles (a run of charges followed by sells), passes each cycle through `cost_gate` at its energy-weighted average buy and sell price, and borrows greedy's hold explanations for hold periods.
- `conservative=True` prices buys at p90 and sells at p10, so it only trades spreads that survive a bad forecast. **It exists but is not used anywhere live.**

**Why greedy is live and not the LP.** Over 100 backtest weeks the LP captured 68.3% vs greedy's 66.4%. The team decided two points wasn't enough to swap the live engine the night before the demo, following the "simple first" principle. It's one flag away: `scripts/decide.py --optimiser lp`.

---

## Part 11: Forecasting (`tempo/forecast/`)

### 11.1 The model ladder

The plan was to climb only as far as the data justifies:

1. **Persistence**: "tomorrow's 6pm = today's 6pm". The baseline any model must beat.
2. **LightGBM**: gradient-boosted trees. The model in use.
3. **Small neural net**: planned, never built. `nn.py` is a three-line stub.

### 11.2 `persistence.py`

- p50 = `price_lag_1d`.
- p10/p90 = p50 ∓ k × `weekly_std`.
- `fit()` picks k as the 80th percentile of |actual − p50| / weekly_std on training rows, so 80% of training prices fall inside the band. A symmetric band, honest overall coverage. `MIN_STD = 1e-6` avoids division by zero on a perfectly flat week.

### 11.3 `lgbm.py`: LightGBM quantile forecaster

- Three separate `LGBMRegressor(objective='quantile', alpha=a)` models for a = 0.1, 0.5, 0.9. The quantile loss (a.k.a. pinball loss) penalises under- and over-predictions asymmetrically so the model learns the a-th percentile instead of the mean.
- Small trees: 300 estimators, 15 leaves, learning rate 0.05.
- Features: the 16 `build_features` columns plus `horizon_k` (how many half-hours ahead the target is, 1..48). The model needs `horizon_k` because a forecast 30 minutes out should be more confident than one 24 hours out.
- **Fully deterministic**: seed 0, one thread, `deterministic=True`, `force_row_wise=True`. The same training rows always give the same model, which the backtest and tests rely on.
- Because the three models are fitted independently, their outputs can **cross** (p10 > p50 for some row). `predict()` sorts each row's three values so p10 ≤ p50 ≤ p90 always holds.
- `save()` / `load()` write `lgbm_p10/p50/p90.joblib`. `load()` reads feature names from the saved models and refuses if the three disagree.

### 11.4 `dataset.py`: building training data without leakage

`make_training_set(conn, decision_times)`:

- For every decision time, calls the **same** `build_features` the live system uses, then adds `horizon_k`.
- y = the actual price at each target time from `prices_hh` (NaN if not settled yet; `fit()` drops those).
- Returns X indexed by `(decision_time, target_time)`.

So the training set can't see the future *by construction*: it's built by asking "what did we know at each past moment?" exactly as live does. `strict=False` skips decision times `build_features` refuses (e.g. too early in the data).

### 11.5 `scripts/train.py` and the real numbers

Trains on the last 90 days, a decision time every 6 h (361 decision times × 48 targets = 17,328 rows). It holds out the last 7 days once to measure, then refits on everything and saves. `models/training.json` records the real run (24 Oct 2026):

```
holdout rows      1,344
p50 MAE           24.45 £/MWh
persistence MAE   33.89 £/MWh      → LightGBM's median error is 28% lower
band coverage     63%              (target 80%)
```

That last number matters: the p10–p90 band held only 63% of real prices on unseen data, so the bands are **too narrow** (overconfident). See Part 20.

---

## Part 12: The live decision engine (`tempo/decide/engine.py`, `scripts/decide.py`)

### 12.1 `run_decision(conn, now, forecaster, optimiser, run_id='live')`

```
build_features(now) → add horizon_k → forecaster.predict → optimiser.plan → decision_rows → write_batch
```

- `battery_from_settings()` builds the battery from config, with SoC from `current_soc()` (latest `battery_state` row for the run) or half capacity.
- `decision_rows()` is pure (no database). It assembles the 48 rows and enforces the contract: action must be one of the three; **mw sign must match the action** (charge > 0, discharge < 0, hold = 0); every hold must have a reason (it fills a default if the optimiser left one blank).
- `write_batch()` first deletes any existing batch with the same `decided_at` and `run_id` (so re-running is a replace, not a duplicate), then inserts 48 forecast rows and 48 decision rows, each decision pointing at its forecast via `forecast_id`. Returns the first decision id.

### 12.2 `scripts/decide.py`

- `--once`: one batch now. `--at …`: one batch at a past time (for rehearsals). Default: loop forever.
- The loop waits until **one minute past each half hour** (`next_slot`), so the newest period's price can be in the features, then runs one cycle with a fresh connection. A failed cycle logs and sleeps 60 s; it never kills the loop.
- Default optimiser is greedy. **Only this script writes run_id `live`.**
- It refuses to start without `models/lgbm_p50.joblib`.

Runs on the backend box under `tempo-decider.service`.

---

## Part 13: The walk-forward backtest (`tempo/backtest/`)

### 13.1 Windows (`walkforward.py`)

`make_windows(start, end, train_days=28, test_days=7)` yields non-overlapping test weeks, each preceded by 28 training days:

```
|--- train 28 d ---|-- test 7 d --|
               |--- train 28 d ---|-- test 7 d --|
                              |--- train 28 d ---|-- test 7 d --|
```

Every test week starts from a fresh default battery, so weeks are independent and each is scored against perfect foresight *on that same week*.

### 13.2 The strategies

A strategy is a function `(train_df, test_df, battery) → schedule_mw` for the test week. `test_df` contains the week's actual prices; strategies may only use them to track the battery's real SoC and for prices already published at decision time. Only `perfect` sees them all.

| Strategy | How it decides |
|---|---|
| `simple_rule` | +1 MW from 01:00 to 05:00, −1 MW from 17:00 to 19:00, UK time, every day. No forecast at all. |
| `persistence_greedy` | Each UK midnight: forecast = same period yesterday (only prices published by then), greedy plan, carry the *real* end-of-day SoC to the next day. |
| `tempo` | LightGBM trained on this window's 28 train days, greedy plan, once per UK day. |
| `tempo_lp` | Same model, LP optimiser. |
| `perfect` | Perfect foresight LP on actual prices. |

Why these baselines? The simple rule tests whether forecasting adds anything over a fixed schedule. Persistence uses the *same optimiser* as Tempo, so the gap between them isolates the value of the model. Perfect sets the ceiling.

### 13.3 `TempoModel`: training without leakage, fast

- Per window, it trains LightGBM on decision times every 6 h through the train days, keeping only decisions whose 48 targets all start before the test week. No label comes from the test week.
- Each test day is planned with one decision a minute before the day's first period, with the real SoC carried over.
- Models and forecasts are cached per window, so `tempo` and `tempo_lp` share one fit.

### 13.4 `features.py`: `FrameConn`, the clever bit

Problem: the backtest needs features at ~3,600 decision times. Each `build_features` call is a round trip to Tiger. That would take hours.

Solution: load everything once into memory (`load_frames`: three queries), then hand `build_features` a **fake connection** (`FrameConn`) that answers its SQL queries from pandas frames. `build_features` runs *unchanged*: same fallbacks, same point-in-time rules. Only the query answers are reimplemented, one function per query (`price_lags`, `price_last`, `daily_rows`, `weekly_rows`, `forecast_rows`, `delay_guard`).

Safety nets:
- If `build_features` ever sends a query `FrameConn` doesn't know, it raises `NotImplementedError`. A new query in `build.py` can't be silently skipped.
- `tests/db/test_backtest_features.py` checks `FrameConn` and the real database give **identical** features.
- `Frames` recomputes daily and weekly aggregates with the same London-day bucketing and the same sample-stddev formula as `schema.sql`, including the Postgres quirk that `greatest(NULL, 0)` is 0.

### 13.5 Scoring (`run_strategy`, `pct_of_perfect`)

For each window: simulate the strategy's schedule and perfect foresight's schedule on actual prices, and store both pnls.

`pct_of_perfect(pnl, perfect)` = 100 × pnl / perfect. If perfect is ~0 (nothing could be earned), holding scores 100% and anything that lost money 0%.

**Why % of perfect and not pounds?** A system can make £500 in a volatile week and £40 in a calm one and be performing identically. The percentage makes weeks comparable. The overall figure is *total* pnl / *total* perfect pnl, so volatile weeks count for more, exactly as the pounds do.

### 13.6 Regimes

`weekly_regimes()` labels each test week **windy** if its mean wind share of demand (WINDFOR / NDF) is above the median week, else **calm**. (Falls back to raw wind MW if NDF doesn't cover every week, so one run has one definition.)

### 13.7 `metrics.py`: turning results into the honesty panel

- `summary()`: one row per strategy with label, weeks, pnl, perfect pnl, % of perfect.
- `by_regime()`: same, split by calm/windy.
- `calibration(forecasts, actuals)`: share of actuals inside [p10, p90] (should be 0.8), and for each quantile the share of actuals at or below it (should be 0.1, 0.5, 0.9), plus a reliability table by p50 decile.
- `weak_statements()`: writes plain-English "where it's weak" lines automatically: where a simpler baseline reaches ≥70% of Tempo's profit or beats it, where Tempo loses money, how far apart its regimes are, and its weakest week.

### 13.8 `replay.py` and `scripts/replay_week.py`

Rebuilds one backtest week period by period (actual price, forecast band, mw, SoC, cumulative £) for the dashboard's Replay section. It picks the **median** windy week for Tempo, deliberately "typical, not the best". The script refuses to write unless the week's final cumulative pnl matches the backtest's number for that week to the penny. The stored week is 11 June 2026: 62.9% of perfect, £611.32.

`per_period_pnl` charges wear as the battery sells, so the running total includes it continuously rather than as a lump at the end.

### 13.9 `scripts/backtest.py`

Runs every strategy over every window and prints the honesty table. `--source db` uses Tiger, `--source synthetic` uses a 60-day fake market. `--write` inserts into `backtest_results` under a time-stamped run id. Synthetic results are never written (they'd sit next to real ones in a shared table).

---

## Part 14: The timing audit (`tempo/audit/`)

The signature mechanic. A forecast can be right while the decision made from it is badly timed. The audit measures that.

### 14.1 Shifting a schedule (`shifts.py: shift_schedule`)

```python
shift_schedule(mw, shift)  # np.roll, but periods that wrap around become hold
```

Positive shift = later. Real output for `mw = [0, 1, 1, 0, −1, −1]`:

```
shift −2   [ 1,  0, −1, −1,  0,  0]
shift −1   [ 1,  1,  0, −1, −1,  0]
shift  0   [ 0,  1,  1,  0, −1, −1]
shift +1   [ 0,  0,  1,  1,  0, −1]
shift +2   [ 0,  0,  0,  1,  1,  0]
```

Notice what falls off the edges: at +2 both sales are gone, at −2 one charge is gone. Keep this in mind when reading audit results (Part 20).

### 14.2 Replaying one shift (`replay_shift`)

```python
replay_shift(conn, decision_id, shift, run_id) -> pnl_gbp
```

1. **Refuses** `run_id='live'`. Replays can never write into the live timeline.
2. `load_schedule`: finds the decision's batch (same `decided_at` and `run_id`) and loads all 48 rows' mw. **The whole batch is shifted, not just the clicked row.**
3. `load_prices`: actual prices for those 48 periods from `prices_hh`. If any is missing, raises `ReplayError` ("a decision can only be replayed once its periods settle").
4. `load_start_soc`: the original run's SoC at `decided_at` from `battery_state`, else half capacity.
5. Shift, simulate, compute cumulative pnl after each period (by running the simulator on prefixes, so it matches the simulator's accounting exactly without re-implementing physics).
6. `write_battery_state`: writes the SoC and cumulative pnl path under `run_id`, at `target_time + 30 min` (end of period). It upserts with `ON CONFLICT`, because two people opening the dashboard at once can run the same self-grade replays.

Same database in, same number out. That determinism is what lets the fork mode be proven equal to the in-process mode.

**The simulator resolution (`refsim.py`).** `resolve_sim()` probes Ernqi's `tempo.sim.battery.simulate`; if it works, use it, else fall back to Ayo's reference copy. Now that Ernqi's module exists, the reference is never used, but the workers report which simulator they run, and `demo_reset` warns if workers and the laptop disagree.

### 14.3 The orchestrator (`orchestrator.py`), two modes

`run_audit(conn, decision_id, mode)` runs shifts −2, −1, 0, +1, +2 and writes five `audits` rows. `pnl_delta_gbp = pnl[shift] − pnl[0]`.

**In-process mode** (`run_inprocess`): calls `replay_shift` five times on the local connection, run ids `audit-<id>-<shift>`. One shift failing never sinks the audit: its row gets `pnl_gbp = NULL` and an error message. This is the on-stage fallback.

**Fork mode** (`run_fork_async`): the real show.

1. **Fork.** Ask Tiger to fork the primary database *now* (`fork_strategy="NOW"`). Wait for READY, then wait until it actually accepts connections (`wait_connectable`, because a Tiger fork can report READY a moment early).
2. **Dispatch.** For each shift, lease a worker from the pool and send `POST /replay {database_url: <fork DSN>, decision_id, shift, run_id}`. The five replays run in parallel, each writing its `battery_state` under its own run id inside the fork.
3. **Collect.** Each result comes back as pnl + worker id. Audit rows are written to the **primary** database (forks only ever hold scratch `battery_state`).
4. **Clean up, always.** In a `finally` block, delete every fork created, then sweep the project for any leftover `audit-<id>-…` service (in case a fork call completed after its shift timed out).

Engineering details worth knowing:
- Every shift has its own timeout (180 s) via `asyncio.timeout`. A timeout becomes a failed row, not a crash.
- In shared mode, the fork-provisioning task is wrapped in `asyncio.shield`, so one shift timing out can't cancel the fork the other four are waiting for.
- Blocking calls (Tiger REST, psycopg) run in a dedicated `ThreadPoolExecutor` that is shut down **without waiting**. `asyncio.to_thread` would use the default executor, which `asyncio.run` joins on exit, so one stuck thread would hold up the whole result.
- Created forks are recorded from *inside* the thread under a lock, so a timeout can't lose track of a fork that needs deleting.
- `AuditProgress` is a thread-safe log of events and per-shift states (`queued → forking → ready → replaying → done/failed`) that the dashboard polls every half second.
- `check_audit_rows()` asserts the contract: exactly shifts −2..2, one decision, one mode, shift 0's delta is exactly 0, deltas consistent with pnls.

### 14.4 Why one fork, not five (the challenge story)

**Plan:** one fork per timeline, five forks per click.

**Reality:** the third fork was refused with `403 ENTITLEMENT_ERROR: "You have reached your free service limit"`. A free Tiger project holds **two services** at once: the primary plus one fork. Paying wouldn't help: the fast copy-on-write forks (36–42 s) only exist on free services; paid forks take 5–20 minutes, useless for a live click.

**Fix:** `forks="shared"` (the default via `TEMPO_AUDIT_FORKS`). One fork per click, frozen at the moment of the click, and all five workers replay *into the same fork concurrently*, each under its own run id. Isolation from live is the same, and from each other is guaranteed by run ids. A test (`tests/db/test_fork_equals_inprocess.py`) proves fork replays equal in-process replays to the penny in **both** layouts. The five-fork code is still there behind `per_shift`.

**Consequences:** nobody may create any other Tiger service on demo day (it would take the audit's slot), and a second click must wait for the first audit to finish (the button is disabled while running).

**Why is the fork "load-bearing" and not decoration?** The replays need to *write* state (`battery_state`) against a frozen copy of the live data, without touching live. A read replica can't be written to; writing into live would pollute it. A writable snapshot is exactly a fork.

### 14.5 The worker (`tempo/worker/main.py`)

A tiny FastAPI app on each Vultr box (port 8000):

- `GET /health` → `{ok, worker_id, simulator, auth, busy, served}`.
- `POST /replay` → connects to the given DSN (8 s timeout, so a bad DSN fails fast with a 500 instead of hanging), calls `replay_shift`, returns pnl + timestamps + worker id + simulator name. A `ReplayError` becomes a 422.
- **Auth:** if `TEMPO_WORKER_TOKEN` is set, requests need `Authorization: Bearer <token>`, checked with `hmac.compare_digest` (constant-time, so timing doesn't leak the token). Without this, anyone could point a public worker at any database.
- **Stateless:** the DSN comes with every request, so workers need no database credentials of their own. `worker_id` comes from the hostname.

### 14.6 The worker pool (`pool.py`)

- `HttpWorkerPool`: a list of `WorkerSlot(worker_id, base_url, region)` and an `asyncio.Queue` of free workers. `replay()` takes a free worker (waiting up to 120 s if all are busy), posts the job, and always puts the worker back. So five shifts on three workers still complete, just queued.
- `from_vultr()`: builds slots from Vultr instances tagged `tempo-worker`.
- `LocalWorkerPool`: the *same* worker app served in-process through an ASGI transport, no network, ids `local-1..5`. Used by tests and as a fallback, named so nobody mistakes it for Vultr on screen.
- `default_pool()`: Vultr via API if configured → else the static list in `TEMPO_WORKER_URLS` (the backend box's IP isn't in Vultr's API allow-list, so it uses this) → else 5 local workers. Returns a note saying which, which the audit log shows.

---

## Part 15: Self-grade (`tempo/audit/selfgrade.py`)

The running scorecard: "Tempo's timing was within one settlement period of hindsight-optimal on X% of cycles."

- A "cycle" = one live batch that both charges and discharges (since replay shifts whole batches).
- For each, replay at shifts −2..+2 (in-process, run ids `selfgrade-<id>-<shift>`) and find the best shift. Ties go to the smallest |shift|.
- `pct_within_one_period` = share whose best shift is −1, 0 or +1.
- `mean_cost_of_mistiming_gbp` = average of (best shift's pnl − actual pnl), always ≥ 0.
- Unsettled batches raise `ReplayError` and are skipped.

The dashboard calls it over the last 30 days. Recorded result in `docs/a.md`: on eight cycles, 100% within one period, mean cost of mistiming £0.51.

---

## Part 16: Pre-demo checks and rehearsal data

### 16.1 `preflight.py` + `scripts/demo_reset.py`: go / no-go

Run before every rehearsal and before going on stage. Each check is OK, WARN or FAIL; any FAIL = NO-GO (exit code 1).

| Check | Fails when | Warns when |
|---|---|---|
| Tiger | primary missing or not READY | primary is PAUSED |
| Stale forks | an `audit-*` fork is left over and can't be deleted | |
| Slots | no free service slot for the audit's fork | |
| Database | unreachable | rehearsal (`selftest`) rows still present |
| Prices | `prices_hh` empty | newest price over 3 h old (poller down?) |
| Decision | no live batch with all 48 periods priced | a shifted timeline beats "as decided" |
| Workers | any worker fails `/health`, or no pool | only local workers ("don't say Vultr"), or fewer than 5 |
| Simulator | | workers run a different simulator than the laptop |

It also **picks the decision to click**: it replays recent live batches in-process and ranks them, preferring ones where "as decided" beats every shift and a hold is nearby, then the biggest +1 cost. It prints the line to say, e.g. "Charging one period later would have cost £14.30". `--fork-test` takes and deletes one real fork and times it.

### 16.2 `rehearsal.py` + `scripts/seed_selftest.py`

Lets you click the fork audit before the live engine has produced settled decisions. It writes one batch of `decisions` under run id `selftest`, for a day ~3 days before the newest price: charge the 4 cheapest periods, sell the 4 dearest after them. Never touches `grid_raw` or aggregates. The dashboard labels it `[rehearsal]`; `demo_reset` warns while it exists; `--remove` deletes it with its audits and battery_state.

---

## Part 17: The dashboard (`tempo/dashboard/`)

### 17.1 Data sources (`data.py`)

Two classes with the **same method names**:

- `SyntheticSource`: deterministic fake data shaped like the real tables (cheap 1–5am, dear 5–7pm, windy even ISO weeks). For local dev and tests.
- `DbSource(conn)`: real queries against Tiger.

`pick_source(url)` uses the database if it's reachable, else synthetic with a banner.

The robust bit is `DbSource._try`: **every method degrades on its own**. If its table is missing or empty (because a teammate's part hadn't landed yet), it returns the synthetic equivalent and records why in `notes[method]`, which shows as a warning under that section. So the page never breaks, and it never silently shows fake data either. Queries are cached for 30 s. A dropped connection reconnects automatically.

Key queries:
- `recent_prices`: last 24 h of `prices_hh`.
- `next_forecast` / `todays_schedule`: the latest live batch.
- `latest_hold`: the most recent hold and its reason.
- `recent_decisions`: non-hold decisions from **settled** batches only (all 48 periods priced), live first, then rehearsal.
- `backtest_*`: the latest backtest run.
- `calibration`: live forecasts that have settled, against actual prices, through `metrics.calibration`.
- `self_grade`, `storage_stats`, `weak_points`.

### 17.2 Background audit jobs (`jobs.py`)

A Streamlit page re-runs top to bottom on every interaction and can't block for 40 s. So `AuditJob` runs `run_audit(mode='fork')` in a **daemon thread with its own database connection** (psycopg connections aren't safe to share across threads), and exposes `progress`, `done`, `rows`, `error`. The page stores the job in `session_state` and a fragment re-renders every 0.5 s until done.

`hero_sentence(rows, action)` writes the one line the presenter reads:
- If a shift beat the real decision: "Charging 30 minutes later would have earned £X more. Tempo mistimed this one." (Honesty is the brand.)
- Else if any shift was worse: "Selling an hour earlier would have cost £X. Tempo picked the best of the five."
- Else: "Shifting this decision by up to an hour would have made no difference."

### 17.3 The page (`app.py`)

One long "report" page, sections in demo order:

1. **Header strip** (refreshes every 30 s): date, current settlement period, UK time, the headline "Tempo captures 66.4% of perfect foresight over 100 unseen weeks", and status dots (Tiger connected? workers healthy, Vultr or local? any synthetic data in use?).
2. **Live**: current period, next action, latest APX price, forecast spread; Fig 1.1 the price chart (last 24 h actual in ink, next 24 h p10–p90 band and p50 in blue, a "now" rule, ▲/▼ action glyphs); Fig 1.2 the 48-period strip coloured by action; the latest hold as a quote card (a hold is shown as a correct decision, not a warning).
3. **Replay**: the stored windy week with a slider; forecast vs actual, state of charge, cumulative £.
4. **Timing audit**: decision picker, mode toggle (fork / in-process), Run button (disabled while running), live per-shift progress cards and log, then results: five PnL cards with deltas, Fig 3.2 diverging bars (red = worse, green = better), the audit log, and the rows written. Then the self-grade line.
5. **Honesty**: Fig 4.1 the backtest ladder (% of perfect per strategy, Tempo in brand green, a dashed line at 100), the table, Fig 4.2 calibration (observed vs nominal, diagonal = perfect), Fig 4.3 calm vs windy, "where it's weak" cards, and the storage/compression line with the stated assumptions.
6. **About**.

The header is rendered **last** into a placeholder at the top, so its "synthetic data in use" dot reflects notes set by the sections below it.

### 17.4 Look and feel (`ui.py`, `theme.py`, `.streamlit/config.toml`)

- `ui.py`: shared pieces (eyebrow labels, serif section headings that are real sentences with real numbers, stat pills, figure labels, the charts).
- `theme.py`: colour tokens (paper `#fafaf8`, ink, brand green `#1a4d3e`, charge green, discharge orange, hold stone, belief blue for forecasts) and a registered Altair theme so every chart shares one grammar and UK local time on the x-axis.
- `config.toml`: Streamlit theme. Fonts (Libre Baskerville, IBM Plex Sans/Mono) are **self-hosted** from `static/`, so venue Wi-Fi can't block them.
- `docs/ui-plan.md` describes a Toven-style two-page design (pitch page + dashboard); `docs/ui.md` holds the chart grammar and audit choreography.

---

## Part 18: Cloud infrastructure and deployment

### 18.1 The boxes

| Box | Where | What runs |
|---|---|---|
| Tiger primary | us-east-1, free service | The database |
| Tiger fork | us-east-1, created per click | Scratch copy for one audit, deleted after |
| `tempo-backend` | Vultr London (`lhr`), `vc2-1c-2gb` | Dashboard (:8501), poller, decision engine |
| `tempo-worker-1..5` | Vultr New Jersey (`ewr`), `vc2-1c-1gb` | Replay workers (:8000) |

Workers sit in `ewr` right next to Tiger's us-east-1, so each replay's database traffic is short-hop. Vultr has no GPU on this account (checked via API), so everything is CPU.

### 18.2 Clients (`tempo/infra/`)

- `tiger.py` / `TigerClient`: Tiger Cloud REST with HTTP Basic auth: `list_services`, `get`, `fork`, `wait_ready`, `delete`, `connection_url`, `delete_all_forks(prefix="audit-")`. A fork's password is only returned once, at creation, so `fork()` keeps it on the `Service` object and `wait_ready()` copies it forward. `sleep` and `clock` are injectable for tests.
- `vultr.py` / `VultrClient`: Vultr v2 REST with Bearer auth: list/create/delete instances, follow pagination cursors, `wait_active`, snapshots, SSH keys, and simple in-memory leasing (`pick_idle`, `lease`). Filters tags client-side too, in case the API ignores the `tag` parameter.
- `deploy.py`: helpers for SSH, rsync (excluding `.env`, `.venv`, `.git`, `models/`), uploading your SSH key, and writing values into `.env`.

### 18.3 Building and launching (`scripts/`)

1. `build_worker_image.py`: upload SSH key → create one build box (tagged `tempo-image`, never `tempo-worker`, so the audit never dispatches to it) → rsync the repo (it's private, so no `git clone`) → run `bootstrap.sh` as a worker → check `/health` and that token auth works → snapshot → delete the build box. Writes `VULTR_SSHKEY_ID`, `TEMPO_WORKER_TOKEN`, `VULTR_WORKER_SNAPSHOT_ID` into `.env`. Costs cents.
2. `create_workers.py`: ensure `tempo-worker-1..5` exist from that snapshot, boot, pass `/health`. Idempotent. `--status`, `--count 3`, `--delete`.
3. `create_backend.py`: create the London box, copy the repo and your `.env`, start the dashboard. `--deploy` redeploys.
4. `time_fork.py`, `time_vultr.py`: Gate 0 measurement scripts (how long does a fork / a box take?).

### 18.4 `deploy/bootstrap.sh` and systemd

`bootstrap.sh` turns a fresh Ubuntu 24.04 box into a Tempo box: installs Python, adds a 2 GB swapfile (1 GB plans need headroom for pip and LightGBM), creates a `tempo` system user, makes a venv and installs the package, writes the worker token to `/etc/tempo/worker.env` (mode 640), installs the systemd units, and opens the firewall (8000 for workers, 8501 for backend). It ends with `sync`, because a snapshot taken seconds later once captured zero-byte unit files (ext4 delayed allocation) and produced a worker image with a broken service.

Four systemd units, all `Restart=always`, logging to `/var/log/tempo/`:

- `tempo-worker`: uvicorn on :8000, `WORKER_ID=$(hostname)`.
- `tempo-dashboard`: Streamlit on :8501.
- `tempo-poller`: `scripts/poll.py`.
- `tempo-decider`: `scripts/decide.py` (greedy on purpose; the comment says "Do not change this on demo day").

### 18.5 Local dev

- `make setup`: venv, install, copy `.env.example`.
- `make db` / `scripts/dev_db.sh`: start `timescale/timescaledb-ha:pg17` in Docker on port 5433 and apply the schema. Safe to run twice; waits for a real query because the image restarts Postgres once after init.
- `make test` (unit + contracts, no network), `make test-db` (needs local DB), `make test-live` (real clouds, costs money), `make lint`, `make dashboard`.

---

## Part 19: The test suite (`tests/`)

### 19.1 The layers

| Folder | Needs | Purpose |
|---|---|---|
| `unit/` | nothing | Pure logic: physics, optimisers, parsing, clients with mocked HTTP (`respx`), dashboard smoke |
| `contracts/` | nothing (mostly) | The frozen interfaces between the three parts: table schemas, decision/audit/battery/feature contracts |
| `db/` | local Docker TimescaleDB | Anything with real SQL: point-in-time, aggregates, backfill, fork equivalence |
| `live/` | `TEMPO_LIVE=1` + real credentials | Real Tiger fork round-trip, full audit, 2-year query on Tiger |
| `fixtures/` | | Synthetic market with known answers, real Elexon JSON samples (including a clock-change day) |

### 19.2 The tests that carry the pitch

These are the ones to name if a judge asks "how do you know?":

- **No lookahead, per column** (`db/test_pit_leak.py`): inserts future rows (a MID price available 40 min after T, forecasts published at T + 1 min, absurd values like 9999) and asserts **nothing** changes; then inserts past rows and asserts the right column **does** change (so the test isn't vacuous). Deleting any `-- pit` line makes it fail.
- **Option A = Option B** (`db/test_option_a_equals_b.py`): recomputes every price feature from `grid_raw` with a true `available_at <= T` join, on 6 weeks of real APX prices across the 26 Oct 2025 clock change, and requires equality with the aggregate-cutoff method. Also proves the delay guard refuses a mismatched constant, and that without the guard a drifted constant really would leak.
- **No lookahead in training** (`db/test_no_lookahead_training.py`, `contracts/test_pit_leak.py`): the same "future rows change nothing" check applied to the training-set builder.
- **Fork = in-process, to the penny** (`db/test_fork_equals_inprocess.py`): "forks" are real copies made with `CREATE DATABASE … TEMPLATE` on local Docker, through a Tiger-shaped fake; workers are the real FastAPI app via `LocalWorkerPool`. All five shifts must match in-process exactly, in both `shared` and `per_shift` layouts.
- **Perfect is an upper bound** (`unit/test_perfect_is_upper_bound.py`): property-based with Hypothesis.
- **Known answers** (`unit/test_synthetic.py`, `fixtures/synthetic.py`): on the synthetic windy week, perfect foresight makes £1,399.6 and the simple rule £1,264.8 (with 15.0 MWh clipped). These were computed with an *independent* reference implementation, not with `tempo/` itself, so they check the code rather than repeat it.
- **Greedy holds on flat prices**, **LP holds on flat**, **cost gate boundaries**, **LGBM beats persistence**, **quantiles never cross**, **clock-change parsing**, **retry/backoff**, **orchestrator with fake clients** (timeouts, failed shifts, cleanup always runs).

---

## Part 20: Things worth knowing before you present

Things I found while reading that aren't obvious from the docs. Some are honest limitations, some are small inconsistencies. None break the demo, but you should know them so a judge's question doesn't surprise you.

1. **The uncertainty bands don't currently affect live decisions.** The pitch says "a wide band means a smaller expected edge, which can tip a marginal cycle into a hold". In code, the greedy optimiser uses **p50 only**. The only thing that uses p10/p90 for decisions is `LPOptimiser(conservative=True)`, which isn't used anywhere. Today the bands feed the chart and the calibration panel. If asked, the honest answer is: "the bands are measured and shown; using them in the gate is the conservative LP mode, built but not switched on."

2. **The bands are overconfident.** The training holdout shows the p10–p90 band held **63%** of actual prices against an 80% target. That's the "calibration" story working as designed (it exposes the problem), but don't claim the bands are well calibrated.

3. **The 80% vs 90% inconsistency in `docs/description.md`.** It says the p10–p90 band should contain "about 90%" of real prices. The correct figure is **80%** (90% − 10%), which is what the code, the persistence model and the dashboard caption use. Say 80%.

4. **The live battery's state of charge isn't tracked between batches.** `run_decision` reads the latest `battery_state` row for run `live`, but nothing in the code writes `battery_state` under `live` (replays are forbidden from it). So every live batch plans from the default half-full battery (1 MWh). There's also a tiny bug: `current_soc(...) or None` turns a genuine 0.0 SoC into "use the default". Neither affects the audit (which also starts from the default), but "today's schedule" is a fresh plan each half hour, not a continuously tracked battery.

5. **The audit shifts the whole 48-period batch, not just the clicked row.** You click one decision, but its entire batch moves. The phrasing "charging 30 minutes later would have cost £X" is really "running this whole plan 30 minutes later would have cost £X".

6. **Edge effects favour "as decided".** Shifting rolls actions off the end of the 48-period window (Part 14.1: at +2, sales near the end of the horizon disappear). A shifted plan can lose a trade just because it fell off the edge, which makes shifts look worse than a fair comparison would. Self-grade inherits this. It's worth knowing if someone asks why "as decided" usually wins.

7. **Backtest cadence differs from live cadence.** The backtest decides once per UK day at midnight; live decides every 30 minutes. Live has fresher information, so the backtest figures are, if anything, conservative for the forecast quality, though the live engine also re-plans from a default SoC each time (point 4).

8. **`MID_DELAY` is hard-coded in `walkforward.py`** as 10 minutes rather than read from config. It matches today, but changing the config wouldn't change the backtest's persistence strategy. (`build_features` and the Tempo strategies do read the config, and the delay guard protects them.)

9. **`forecast/nn.py` is an empty stub.** The neural net rung of the ladder was never built. The pitch already handles this ("kept only if it beats LightGBM"); just don't imply it was tried.

10. **The demo-day rules** (from the README) exist because of the free-tier limit: nobody creates Tiger services on demo day, click the audit once and wait, and if the fork fails switch the toggle to in-process and say "same replay, run locally".

---

## Part 21: Check your understanding

Try to answer before reading the answer.

**1. Why does `grid_raw`'s primary key include `available_at`?**
So the same target period can have several rows, one per publication. That's what lets the system ask "what did we know at time T?" and get the version published before T.

**2. MID has no publish time. How does Tempo stop future prices leaking in?**
At ingest it stamps `available_at = start + 30 min + 10 min`. `build_features` then only uses price buckets whose start is ≤ T − 40 min, and refuses to run if the stored offset doesn't match the configured delay.

**3. Why does WINDFOR forward-fill instead of interpolating between hours?**
Interpolating 10:30 needs the 11:00 forecast, which may not have been published at decision time. That would leak.

**4. A battery at 1 MWh charges 1 MW for one period at £40. What's the SoC after, and what did it cost?**
Bought 0.5 MWh for £20; stored 0.5 × 0.9487 = 0.474 MWh; SoC ≈ 1.474 MWh.

**5. Buy at £50, sell at £65. Does the cost gate allow it? Why?**
No. Spread £15; cost = 10% of £65 (£6.50) + £9 degradation = £15.50 > £15.

**6. Why report "% of perfect foresight" instead of pounds?**
Pounds swing with how volatile the week was. The percentage makes calm and volatile weeks comparable, and the ceiling makes the number honest.

**7. What does the persistence + greedy row isolate?**
The value of the forecasting model, since it uses the same optimiser as Tempo. The gap (52.9% → 66.4%) is the model's contribution.

**8. What is `FrameConn` and why does it exist?**
A fake database connection that answers `build_features`' SQL from in-memory frames, so the backtest runs the real feature code thousands of times without thousands of round trips to Tiger. A test checks it gives identical features to the real database.

**9. Why is the timing audit one fork and not five?**
Tiger's free tier allows two services (primary + one fork). Fast forks only exist on free services. So one fork per click, five workers replaying into it under separate run ids, proven equal to the penny.

**10. Why is a fork needed at all? Why not replay on the live database?**
Replays write `battery_state`. Writing into live would pollute it; a read replica can't be written. A fork is a writable, frozen copy of live at the moment of the click.

**11. What happens if one of the five shifts fails on stage?**
Its row is written with `pnl_gbp = NULL` and an error, the other four still render, and every fork is still deleted in the `finally` block. If the fork itself fails, switch the toggle to in-process.

**12. Why does greedy run live when the LP scored higher?**
68.3% vs 66.4% over 100 weeks wasn't judged enough to swap the night before the demo; the team follows "simple first". It's one flag (`--optimiser lp`).

**13. What does `-- pit` mean in `build.py`, and how is it tested?**
It marks each point-in-time filter line. The leak test was run with each line deleted in turn and must fail every time, proving each filter matters.

**14. How does the backfill know what's already loaded, and why not just check for rows?**
`ingest_log`, written in the same transaction as the data. Checking for rows failed because Elexon returns whole days, so each window spilled into the next and made it look loaded; half of MID was silently skipped that way.

**15. Why are the fonts self-hosted?**
So venue Wi-Fi blocking Google Fonts can't break the dashboard's look during the demo.

---

*Written from a full read of the repository on branch `ayo` at commit `a540027`, 24 Oct 2026. Worked examples were run against the code in `.venv`.*
