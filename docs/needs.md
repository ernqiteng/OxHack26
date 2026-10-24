# Tempo: setup needs and feasibility check

Everything below was verified on 24 October 2026 by hitting the real APIs and reading the vendors' current docs. Items marked **unverified** could not be confirmed and must be checked at Gate 0.

---

## Part A: Feasibility verdict on description.md

**Overall: feasible.** The data exists, is free, goes back two years, and carries publish times. Tiger Data exposes a REST fork endpoint. Vultr exposes an instance-creation API. LightGBM and cvxpy are standard. Five things in description.md need adjusting before they are true.

### A1. Zero-copy forks are only fast on Tiger *free* services

Tiger's own fork docs give two different numbers:

| Service type | Fork mechanism | Fork creation time |
|---|---|---|
| Free service | Copy-on-write ("Fluid Storage"), zero-copy | **30 to 90 seconds** |
| Standard (paid) service | Backup restore + WAL replay | **5 to 20+ minutes** |

The "click a decision, fork spins up live" demo only works if the live database is a **free service**. (Originally five forks per click; the free tier allows only 2 services per project, so it is one fork per click. See B2 and description.md section 11.) A standard service fork would take longer than the whole demo. Free services are in beta, run only in `us-east-1`, and exclude tiering, replication, connection pooling, VPC and metrics. You can fork free → free or free → standard, but **not** standard → free. Fork is only allowed when the parent is in `READY` or `PAUSED` state.

**Decision for Gate 0:** run the primary Tempo database as a free service so forks are seconds, not minutes. If free-service storage turns out too small for two years of raw data (limit **unverified**, see B2), keep raw history on a standard service and keep a slim "decision state" free service that forks fast. Fallback if forks are slow on the day: pre-create the fork before the demo and have the click dispatch workers into it.

**Also:** "run the audit automatically on every completed cycle" implies several forks per day. Do the automatic self-grade as in-process backtest shifts (no forks) and reserve real forks for the on-stage click. Update section 3, Layer 2 accordingly.

### A2. Market Index Data has no publish time

The `MID` dataset rows contain `startTime`, `settlementDate`, `settlementPeriod`, `dataProvider`, `price`, `volume` and **no `publishTime`**. The "every row stamped with when it was published" claim holds for WINDFOR, NDF, FUELINST, FUELHH and INDO (all carry `publishTime`), and for system prices (`createdDateTime`), but not for MID.

**Fix:** stamp MID rows with a derived `available_at = startTime + 30 min + δ`, where δ is a stated assumption (MID is reported by the exchanges shortly after the period closes). Say this explicitly in the honesty panel. Section 3 and section 9 ("Lookahead bugs") should say "publish time where the source provides it, derived availability time for MID".

### A3. Price series: pick APX MID, and say what "trading at it" means

- `N2EXMIDP` rows are frequently `price: 0.00, volume: 0.000` (observed in live data). Filter to `dataProviders=APXMIDP` or you will train on zeros.
- System price (`DISEBSP`) `createdDateTime` in live data is roughly **24 hours after** the period it describes. It is an imbalance cash-out price, not a tradeable price.
- Neither series is a price a battery can lock in ahead of time (that would be the day-ahead auction, which Elexon does not publish). For the hackathon the honest framing is: "we assume the battery can transact at the APX within-day index price for each period." Write that assumption into the honesty panel and resolve the Gate 0 "MID vs system price" decision as **APX MID**.

### A4. Non-stream Elexon endpoints are capped at 7 days per request

Tested and confirmed: `/datasets/{X}`, `/balancing/pricing/market-index` and `/balancing/settlement/system-prices/{date}` reject ranges over 7 days (or one settlement date). The `/datasets/{X}/stream` variants returned 60 days, and `/datasets/MID/stream` returned a **full year in one call** (5.6 MB, under a second). Use the stream endpoints for the bulk load. System prices have no stream endpoint, so the two-year backfill is ~730 one-day calls.

### A5. Wind forecast is hourly, not half-hourly

`WINDFOR` rows have hourly `startTime` values. The feature pipeline must interpolate or forward-fill to settlement periods. Minor, but the description currently implies everything is half-hourly.

### Everything else checks out

| Claim in description.md | Status |
|---|---|
| Elexon API is free, no key | **Confirmed.** 15 back-to-back requests, all 200. |
| 48 settlement periods, new data during demo | **Confirmed.** `datasets/metadata/latest` shows FUELINST/FUELHH updating every 30 min. |
| Two years of history | **Confirmed** for MID, WINDFOR, FUELHH, NDF and system prices (October 2024 returns data). |
| Tiger hypertables, continuous aggregates, hierarchical aggregates, compression | Standard TimescaleDB features, all current. Hierarchical aggregates (aggregate on aggregate) are supported. The compression API is now called "columnstore" in docs newer than TimescaleDB 2.18; both names work. |
| Tiger zero-copy forks via API | **Confirmed.** `POST /projects/{project_id}/services/{service_id}/forkService`. See A1 for the speed caveat. |
| Vultr workers provisioned via API | **Confirmed.** Bearer-token REST API, 30 requests/second per IP. See B4 for account-limit caveat. |
| Vultr GPU for neural net | **Unverified.** GPU plan availability and quota on a new account could not be confirmed. The description already handles this ("train on CPU if not"). |
| "X million rows" on screen | **Realistic.** See B3 for row estimates (about 10 million rows over two years if FUELINST is included). |
| LightGBM quantiles p10/p50/p90 | Standard: three LightGBM models with `objective="quantile"` and `alpha` 0.1/0.5/0.9. |
| cvxpy LP, 48 periods | Trivial problem size, solves in milliseconds with the default solver. |

---

## Part B: What has to be set up

### B1. Accounts, keys and secrets

| Service | What you need | Where to get it | Notes |
|---|---|---|---|
| **Elexon Insights API** | Nothing | https://data.elexon.co.uk/bmrs/api/v1 | No key, no registration. Spec returns `429 too many requests` as a possible response, limit is undocumented. Be polite in the bulk loader (one request in flight, short sleep). |
| **Tiger Cloud** (Tiger Data) | Account, project ID, client credentials (access key + secret key) | Tiger Console → project settings → client credentials | REST API uses HTTP Basic auth: `-u "$TIGERDATA_ACCESS_KEY:$TIGERDATA_SECRET_KEY"`. Base URL `https://console.cloud.tigerdata.com/public/api/v1`. New accounts get a 30-day Performance-plan trial, no card needed. Also install the CLI (`brew install timescale/tap/tiger`, then `tiger auth login`) for quick manual forks. |
| **Vultr** | Account with billing, API key | Customer Portal → Account → API | Header `Authorization: Bearer $VULTR_API_KEY`, base URL `https://api.vultr.com/v2`. The key's Access Control list defaults to "Any IPv4 / Any IPv6"; leave that on for the hackathon or add the venue's egress subnet. Keys cannot be scoped per product. |
| **Git hosting** | Repo | Already exists | Add a `.env.example`; never commit real keys. |

### B2. Tiger Cloud: decisions and unknowns to resolve at Gate 0

- [x] Create a **free service** as the primary database (fast forks). Region will be `us-east-1`. **Done 2026-10-24:** `db-40426`, service ID `g7kw81aat8`, project `hpcbhmyhmj`.
- [x] Free-service storage cap: **750 MiB** (Console pricing panel, shared compute, $0/hr). **Already 339 MB used on an empty database** (API `metrics.storage_mb`), so only ~410 MiB is left for data. Compression is on from the start (schema.sql). **Full NDF history confirmed** (Girik + Ernqi, 24 Oct): a local 2-year load of all six datasets (3.32M rows, 730/730 days each) is **65.5 MiB** `pg_database_size` once chunks are compressed, reindexed and vacuumed (~14 B/row). FUELINST stays skipped. **Two storage numbers, do not mix them up:** the cap is enforced on Tiger's API `metrics.storage_mb`, which includes the ~340 MB baseline; `pg_database_size` does not (at the pause: `storage_mb` 515 vs `pg_database_size` 147 MiB). Any storage guard must read `storage_mb`. **Tiger backfill paused 24 Oct** with MID, DISEBSP, INDO, WINDFOR, FUELHH complete and NDF at 4/13 windows, because the loader compressed only after each whole dataset and the remaining NDF windows would have sat uncompressed past the cap; it resumes (via `ingest_log`) once compression runs per window. **Free services per project: 2** (verified 2026-10-24, Ayo): primary + one fork works; a third service gets `403 ENTITLEMENT_ERROR "You have reached your free service limit"`. Five forks per audit is impossible on this account, so the timing audit defaults to one fork per audit with the five timelines replayed inside it under their own run_ids (`TEMPO_AUDIT_FORKS=shared`). Measured: fork READY 36 to 42 s, five replays +1.3 s, an immediate second audit succeeds (the deleted fork frees its slot in time). `per_shift` stays available if Tiger raises the limit.
- [x] Confirm `timescaledb` extension version and that `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)` and hierarchical aggregates work on the free tier. **Verified 2026-10-24:** PostgreSQL 18.6, TimescaleDB 2.31.0; a 1h cagg and a 1d cagg built on top of it both work. Drop hierarchical caggs top-down (1d before 1h), `DROP TABLE ... CASCADE` won't do it.
- [x] Confirm compression / columnstore policies are allowed on the free tier. **Verified:** `ALTER TABLE ... SET (timescaledb.enable_columnstore = true)`, `compress_chunk()`, and `CALL add_columnstore_policy(...)` all work. Note `add_columnstore_policy` is a procedure in 2.31: use `CALL`, not `SELECT`.
- [x] Time one fork end to end with `fork_strategy: "NOW"` and one with `"LAST_SNAPSHOT"` and record the numbers. `LAST_SNAPSHOT` is faster but can be up to an hour stale; `NOW` takes a fresh snapshot. For the timing audit `NOW` is what you want. **Measured 2026-10-24 with `scripts/time_fork.py` on an empty database:** `NOW` 34.8s to READY, `LAST_SNAPSHOT` 25.9s (API accepts the request in ~1s, fork starts `QUEUED`). Re-run after the backfill to confirm it holds with real data.
- [x] Note the fork response: it returns `service_id`, `initial_password`, `endpoint.host`, `endpoint.port` and `status`. Poll `GET /projects/{project_id}/services/{service_id}` until `status == "READY"` before connecting. **Verified:** status goes `QUEUED` → `READY`.
- [x] Delete forks after each audit: `DELETE /projects/{project_id}/services/{service_id}`. **Verified:** works, `scripts/time_fork.py` deletes its fork by default.

Fork request body (verified from the REST reference):

```json
POST /projects/{project_id}/services/{service_id}/forkService
{
  "fork_strategy": "NOW",
  "name": "audit-<decision_id>-shift-minus2",
  "environment_tag": "DEV"
}
```

### B3. Data: exact endpoints, volumes and quirks

All under `https://data.elexon.co.uk/bmrs/api/v1`. All return JSON. Use `/stream` for history, the non-stream form for live polling (it accepts `format=csv` too).

| Purpose | Endpoint for history (bulk) | Endpoint for live polling | Row key fields | Publish-time field | Est. rows / 2 years |
|---|---|---|---|---|---|
| **Price** (chosen series) | `/datasets/MID/stream?from=&to=&dataProviders=APXMIDP` (one year per call works) | `/balancing/pricing/market-index?from=&to=&dataProviders=APXMIDP` (≤7 days) | `startTime`, `settlementDate`, `settlementPeriod`, `price`, `volume` | **none** (derive, see A2) | ~35k (APX only) / ~70k (both) |
| System price (reference only) | `/balancing/settlement/system-prices/{YYYY-MM-DD}` (one day per call, ~730 calls) | same | `settlementPeriod`, `systemSellPrice` (= buy price now), `netImbalanceVolume` | `createdDateTime` (~24h lag) | ~35k |
| Wind forecast | `/datasets/WINDFOR/stream?publishDateTimeFrom=&publishDateTimeTo=` | `/forecast/generation/wind/latest?from=&to=` | `startTime` (hourly), `generation` MW | `publishTime` | ~430k |
| Demand forecast (day-ahead) | `/datasets/NDF/stream?publishDateTimeFrom=&publishDateTimeTo=` | `/forecast/demand/day-ahead/latest?from=&to=` | `startTime`, `settlementPeriod`, `demand` MW, `boundary` | `publishTime` | ~2.1M (re-published every 30 min, heavy) |
| Actual demand | `/demand/outturn/stream?settlementDateFrom=&settlementDateTo=` | `/datasets/INDO` | `startTime`, `settlementPeriod`, `demand` | `publishTime` | ~35k |
| Generation mix, half-hourly | `/datasets/FUELHH/stream?publishDateTimeFrom=&publishDateTimeTo=` | `/datasets/FUELHH?publishDateTimeFrom=&publishDateTimeTo=` | `startTime`, `settlementPeriod`, `fuelType`, `generation` | `publishTime` | ~700k |
| Generation mix, 5-minute (optional, for the row count) | `/datasets/FUELINST/stream?...` | `/datasets/FUELINST?...` | as above, 5-min `startTime` | `publishTime` | ~8M |
| Freshness check | `/datasets/metadata/latest` | same | `dataset`, `lastUpdated` | | |

Quirks to code around:

- **7-day cap** on every non-stream endpoint. Stream endpoints returned 60 days and 1 year without complaint, but keep bulk calls to ~30 to 90 days each so a single failure is cheap to retry.
- **N2EX MID rows with zero price/volume.** Filter to `APXMIDP`, or drop rows with `volume == 0`. Do both: APX alone still had 12 zero-volume rows in the year to 2026-10-24.
- **`settlementPeriod` is UK local time.** In BST, `startTime 00:00Z` is SP 3 (SP 1 is 23:00Z the previous day). The year of MID contained one SP 49 and one SP 50 (26 Oct 2025 clock change). Another reason to key on `startTime`.
- **Settlement periods 49 and 50** exist on clock-change days (the API notes this). October 25 2026 is a clock-change day in the UK, which is during OxHack. Key rows on `startTime` (UTC), not `(settlementDate, settlementPeriod)`.
- **NDF volume.** Two years of NDF is about 30 MB per 60 days ≈ 360 MB JSON. Either load only the latest forecast per `startTime` published before each decision time, or load it all and let compression handle it. It is the dataset that makes the "millions of rows, compressed Y%" line true.
- **WINDFOR is hourly.** Forward-fill or interpolate to half-hours.
- **Rate limit undocumented.** Spec declares a 429 response. The bulk loader should back off on 429 and never run more than one or two requests concurrently.
- **Timestamps are UTC with `Z`.** Settlement periods are defined in UK local time (period 1 starts 00:00 local). Keep everything in UTC in the database and convert only for display.

### B4. Vultr: decisions and unknowns to resolve at Gate 0

- [ ] **Account limits.** Vultr caps the number of instances and spend on new accounts, raised only via a limit-increase request that support reviews manually. Check Billing → Limits on day one. You need at least **5 worker instances + 1 backend** running at once. Request an increase immediately if the cap is lower.
- [x] **Region.** Decided: workers `ewr`, backend `lhr` (B8 item 4). Pick one close to the Tiger service (`us-east-1` for a free service → Vultr New Jersey `ewr`) to keep fork-to-worker latency low. The venue is in Oxford, so the dashboard backend is better in London (`lhr`); workers can be in `ewr`.
- [x] **GPU availability: not possible on this account (re-checked 24 Oct 2026 evening via API).** `GET /v2/plans?type=vcg` lists three NVIDIA L40S cloud GPU plans ($1.67 to $6.68/h) and `GET /v2/plans-metal` lists nine GPU bare-metal plans (A100, H100, L40S, GH200, B200, MI300X and others). **Every one has an empty `locations` list**, and `GET /v2/regions/{id}/availability?type=vcg` returns no GPU plan in any of the 33 regions. Older fractional plans (A16, A40, A100 slices) are no longer listed at all. Because this is true for every GPU type in every region, it is account gating (new account on a $105 credit) rather than a regional stock-out. Vultr raises limits only through a manually reviewed request (Portal → Account → Limits → Request Limit Increase, or a support ticket) and expects billing history, so it will not land during the hackathon. **Decision: train on CPU. The pitch does not mention GPU.** The Vultr story is the worker pool, parallel backtests and hosting. A ticket is still worth filing for the record: ask for `vcg-l40s-16c-180g-48vram` in `ewr` or `lhr` for one day, state the hackathon use, and note the $105 credit.
- [x] **Boot timing (verified 24 Oct 2026):** `vc2-1c-1gb` ($5/mo, $0.0068/h) in `lhr` (the backend region; workers go in `ewr` per the region decision, expect similar), Ubuntu 24.04 (`os_id` 2284): created → `active/running/ok` in **39 s**, SSH port open at **78 s**. API key confirmed working (`/v2/account` shows the $105 credit as balance −105). `lhr`, `ewr`, `ams`, `fra`, `cdg` all available; the sub-$5 plans (`vc2-1c-0.5gb*`) are not offered in `lhr`.
- [ ] **Pre-warm pool.** Measured boot is ~40 s to running and ~80 s to SSH, before any cloud-init; still too slow to create on click. Create the 5 workers before the demo, keep them running, and have the click trigger a *job* via the API (or a tiny HTTP call to each worker) rather than instance creation. Still show the real Vultr API being called (for example `GET /v2/instances` to pick an idle worker, or a snapshot-based create that was started earlier).
- [ ] **Worker image.** Build one worker, snapshot it (`POST /v2/snapshots` with `instance_id`), and create the pool from the snapshot with `snapshot_id` plus `user_data` (base64 cloud-init) that injects the Tiger credentials.
- [ ] **Cost sanity.** Smallest shared-CPU plans are roughly $0.01/hour each. Five workers for 36 hours is a few dollars.

Create-instance call (standard Vultr v2 API):

```http
POST https://api.vultr.com/v2/instances
Authorization: Bearer $VULTR_API_KEY
Content-Type: application/json

{
  "region": "ewr",
  "plan": "vc2-1c-1gb",
  "snapshot_id": "<worker-snapshot-id>",
  "label": "tempo-worker-1",
  "hostname": "tempo-worker-1",
  "sshkey_id": ["<ssh-key-id>"],
  "user_data": "<base64 cloud-init>",
  "tags": ["tempo", "worker"]
}
```

Rate limit: 30 requests per second per source IP, 429 above that.

### B5. Software and libraries

| Component | Package | Notes |
|---|---|---|
| Python | 3.11+ | |
| HTTP | `httpx` or `requests` | For Elexon, Tiger REST, Vultr REST |
| Database driver | `psycopg[binary]` (v3) | Hypertable writes, `COPY` for bulk load |
| Data frames | `pandas`, `pyarrow` | |
| Forecasting | `lightgbm` | Three models for p10/p50/p90, `objective="quantile"` |
| Optimiser | `cvxpy` + default solver (`CLARABEL` ships with it; `ECOS`/`SCS` also fine) | 48×3 variables, instant |
| Neural net (optional) | `torch` | Only if Vultr GPU is available |
| Backtest / metrics | `numpy`, `scikit-learn` (for calibration curves) | |
| Dashboard | Any: `streamlit` is fastest; FastAPI + a small frontend if you want click-to-fork wired cleanly | |
| Scheduling | `apscheduler` or a `while True: sleep(60)` poller | Poll `datasets/metadata/latest`, fetch only when `lastUpdated` moves |
| Secrets | `python-dotenv` | |
| Tiger CLI (optional) | `brew install timescale/tap/tiger` | Manual forks and `tiger db connect` for debugging |

### B6. Environment variables

```
# Tiger Cloud
TIGERDATA_PROJECT_ID=
TIGERDATA_ACCESS_KEY=
TIGERDATA_SECRET_KEY=
TIGER_PRIMARY_SERVICE_ID=
TEMPO_DATABASE_URL=postgres://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require

# Vultr
VULTR_API_KEY=
VULTR_REGION=ewr
VULTR_WORKER_PLAN=vc2-1c-1gb
VULTR_WORKER_SNAPSHOT_ID=
VULTR_SSHKEY_ID=

# Tempo
ELEXON_BASE_URL=https://data.elexon.co.uk/bmrs/api/v1
PRICE_PROVIDER=APXMIDP
BATTERY_CAPACITY_MWH=2
BATTERY_POWER_MW=1
BATTERY_RT_EFFICIENCY=0.90
BATTERY_CYCLE_COST_GBP=20
MID_AVAILABILITY_DELAY_MIN=10     # the δ from A2, state it on screen
```

### B7. Database objects to create (so the description's claims are true)

| Object | Type | Purpose |
|---|---|---|
| `grid_raw` (or one table per dataset) | hypertable on `start_time`, with `published_at` column | Raw Elexon rows, publish-time stamped |
| `prices_hh` | continuous aggregate, 30 min | Half-hourly APX MID price |
| `prices_daily` | continuous aggregate on `prices_hh`, 1 day | Daily spread, mean (hierarchical) |
| `prices_weekly` | continuous aggregate on `prices_daily`, 1 week | Weekly volatility / regime (hierarchical) |
| `forecasts` | hypertable | 48-period p10/p50/p90 per decision time |
| `decisions` | hypertable | `decided_at`, `target_period`, `action` (charge/discharge/hold), `reason`, `forecast_id`, `expected_spread`, `soc_before`, `soc_after` |
| `battery_state` | hypertable | SoC and cumulative PnL per period (this is what forks write to) |
| `audits` | hypertable | One row per (decision, shift), `pnl_delta_gbp`, `fork_service_id`, `worker_id`, timings |
| `backtest_results` | plain table | The honesty table rows |
| Compression policy | on `grid_raw` chunks older than 7 days | For the "compressed Y%" number |

**Measured on Tiger, 24 Oct 2026 evening (Girik, Phase 3):**

- **Storage line for the dashboard** (`storage_stats()`): 3,325,057 rows in `grid_raw`, 105 of 107 chunks compressed, **30.1 MiB → 6.5 MiB, 4.6× (78% saved)**. Database 66.7 MiB by `pg_database_size`; Tiger's `metrics.storage_mb` (what the 750 MB cap is enforced on) **453 of 750**. `storage_stats()` takes ~0.75 s on Tiger from a laptop, so cache it (the dashboard does, 30 s).
- **Two-year query** `SELECT bucket, price FROM prices_hh ORDER BY bucket` (35,056 rows): **executes in 19 ms on Tiger** (`EXPLAIN ANALYZE`, planning 0.7 ms). Fetching the rows to a laptop ~280 ms from us-east-1 took **5 to 36 s**: the network, not the database (binary protocol no better). Locally it is 48 ms end to end.
- **Therefore draw two-year charts from the aggregates**: `prices_daily` (731 rows, mean/min/max) fetched in **0.65 s** from the same laptop, `prices_weekly` (105 rows) in 0.39 s. Keep `prices_hh` for windows up to a week: the Live tab's 24 h query is 0.26 s, 168 h 0.71 s. This is the hierarchical-aggregate story for the Tiger pitch: "the full two-year query runs in 19 ms; the chart reads the daily rollup, so it is instant anywhere."
- Pinned by `tests/db/test_two_year_query.py` (local full backfill, < 1 s end to end) and `tests/live/test_two_year_query_tiger.py` (`TEMPO_LIVE=1`: Tiger execution < 1 s, daily chart fetch < 2 s).

### B8. Gate 0 checklist (do these in the first hour)

1. [x] Tiger: create free service, note storage cap, create client credentials, run one fork via REST and time it. Cap 750 MiB (339 MB used empty, see B2). Forks: 34.8s `NOW`, 25.9s `LAST_SNAPSHOT`.
2. [ ] Vultr: create API key, check account instance limit, list GPU plans, deploy one tiny instance and time boot-to-ready.
3. [x] Elexon: run the one-year `MID/stream` call and a one-week `NDF/stream` call, confirm shapes match the table in B3. **Done 2026-10-24, shapes match.** Both return a bare JSON list (no `data` wrapper), newest first. MID 1 year APX: 17,521 rows, 2.8 MB, 6.9s. NDF 1 week: 19,768 rows, 3.4 MB, 8.7s, 334 publishes (every ~30 min), all `boundary: "N"`. Extrapolates to ~2.1M rows / ~350 MB JSON for 2 years, matching B3.
4. [x] Decide and write down: **APX MID** as the price, MID availability delay δ, battery parameters, Vultr region. **Decided 2026-10-24:**
   - **Price:** APX MID (`dataProviders=APXMIDP`), dropping `volume == 0` rows.
   - **δ = 10 min**, so `available_at = startTime + 40 min`. Shown in the honesty panel as an assumption.
   - **Battery:** 2 MWh, 1 MW, 90% round-trip (split as √0.9 each way), £20 per full cycle, start at 1 MWh (50% SoC).
   - **Vultr region:** workers in `ewr` (New Jersey, next to Tiger `us-east-1`), dashboard backend in `lhr` (London).
   - All match `.env.example`, `docs/plan.md` (`Battery`) and `docs/description.md`.
5. [x] Confirm UK clock change on 25 Oct 2026 is handled (period 49/50 on that date). **Checked 2026-10-24** against real MID for the last clock change (26 Oct 2025), saved as `tests/fixtures/elexon_samples/mid_2025-10-26_clock_change.json`: 50 rows, 50 distinct `startTime`, SP 1 to 50, no collisions. The design handles it (schema keys on UTC `start_time`, girik.md says never derive `start_time` from SP). Ingest code is still a stub, so `tests/unit/test_clock_change.py` (girik.md) must run against this fixture once `normalise` exists. Rules for everyone:
   - **Never compute a settlement period from the UTC clock.** It mismatched all 50 rows that day, and is off by 2 every day in BST. SP = half-hours since UK local midnight + 1. Fixed in ayo.md (dashboard Live tab).
   - **Horizons are 48 half-hours from now, not "one settlement day".** A clock-change day has 46 or 50 periods.
   - **`ZoneInfo("Europe/London")` fails on Windows without the `tzdata` package.** Added to `pyproject.toml`.
   - **Say which clock local-time rules use.** `simple_rule` (charge 01:00 to 05:00, discharge 17:00 to 19:00) and features like `hour` / `period_of_day` should use UK local time, or state UTC explicitly.
6. [x] Put `.env.example` in the repo with every variable from B6. **Checked 2026-10-24:** all 17 B6 variables present, plus the test DB URL and `TEMPO_LIVE`.
