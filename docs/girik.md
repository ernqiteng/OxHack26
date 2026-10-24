# Part A: Data (Girik)

Gate reached: _(write date/time here as you pass each gate)_

You own everything between Elexon and the feature DataFrame. If your part is right, nobody downstream can accidentally use the future. If it is wrong, every number on the honesty panel is a lie, so your tests are the most adversarial in the repo.

**You own:** `tempo/db/`, `tempo/ingest/`, `tempo/features/`, `tests/fixtures/elexon_samples/`, `scripts/dev_db.sh`, `scripts/backfill.py`, `scripts/poll.py`.

**You depend on:** nothing. Ernqi's synthetic fixture is useful for testing `build_features` before the backfill finishes.

**Others depend on you for:** `schema.sql` (everyone, from Phase 0), `prices_hh` on Tiger (Ernqi's backtest, Ayo's dashboard, Phase 1 exit), `build_features` (Ernqi's `run_decision`, Phase 2).

Endpoint details, volumes and quirks are in [needs.md](needs.md) section B3. Read it before writing the client.

---

## Phase 0: Schema and local DB (~90 min)

### Tasks

1. `scripts/dev_db.sh`: start `timescale/timescaledb-ha:pg17` in Docker on port 5433, wait for ready, apply `tempo/db/schema.sql`. Idempotent (safe to run twice).
2. `tempo/db/schema.sql`: every table from plan.md section 2.1 as hypertables, plus the three continuous aggregates and their refresh policies. Use `time_bucket('30 minutes', start_time)` for `prices_hh`, filtered to `dataset='MID' AND series='APXMIDP'`. `prices_daily` is defined on `prices_hh`, `prices_weekly` on `prices_daily` (hierarchical).
3. `tempo/db/conn.py`: `get_conn()` from `TEMPO_DATABASE_URL`, `copy_rows(conn, table, rows)` using psycopg 3 `COPY` for bulk inserts, `upsert_grid_raw(conn, df)` using `ON CONFLICT DO NOTHING` on the primary key.
4. Create the Tiger free service, apply the schema there too. Note the storage cap you see in the console in needs.md B2.

### Tests

- `tests/contracts/test_schema.py` (shared, you write it): apply schema to Docker DB, assert all tables are hypertables (`timescaledb_information.hypertables`), assert the three aggregates exist and `prices_daily` is defined on `prices_hh` (query `timescaledb_information.continuous_aggregates`).
- `tests/db/test_conn.py`: `copy_rows` of 10k synthetic rows under 2 s; `upsert_grid_raw` twice yields the same count.

### Exit

Schema applied locally and on Tiger. Contract test green. Freeze the schema with the others.

---

## Phase 1: Backfill two years (Gate 1, ~4 h)

### Tasks

1. `tempo/ingest/elexon.py`:
   - `fetch_stream(dataset, **params) -> list[dict]` for `/datasets/{X}/stream`, and `fetch(dataset, **params)` for the non-stream form.
   - `chunk_range(start, end, days)` yields date windows. Stream calls use 60-day windows (MID can do a year, but keep retries cheap). Non-stream calls use ≤ 7 days.
   - Retry with backoff on 429 and 5xx, max one request in flight.
   - `normalise(dataset, rows) -> DataFrame` in `grid_raw` long format. Rules:
     - `MID`: `series = dataProvider`, `value = price`, keep `volume` as a second row with `series='APXMIDP:volume'` (or a separate column, your call, but document it). `available_at = startTime + 30 min + MID_AVAILABILITY_DELAY_MIN`. Drop rows with `volume == 0`.
     - `WINDFOR`: `series=''`, `value=generation`, `available_at=publishTime`. Hourly `startTime` stays hourly in `grid_raw`; interpolation happens in features.
     - `NDF`: `series=boundary`, `value=demand`, `available_at=publishTime`.
     - `INDO` (via `/demand/outturn/stream`): `series=''`, `value=demand`, `available_at=publishTime`.
     - `FUELHH`: `series=fuelType`, `value=generation`, `available_at=publishTime`.
     - `DISEBSP` (via `/balancing/settlement/system-prices/{date}`): `series=''`, `value=systemSellPrice`, `available_at=createdDateTime`.
   - Parse all timestamps as UTC. Never use `settlementDate + settlementPeriod` to compute `start_time`; use the API's `startTime`.
2. `tempo/ingest/backfill.py`: loads each dataset for `[today - 730 days, today]` into the DB, logs rows per dataset, resumable (skips windows already present, keyed on `available_at` range).
3. Save one real response per dataset (one day) into `tests/fixtures/elexon_samples/` for the unit tests. Include a sample from 25 October 2026 or 26 October 2025 that contains settlement periods 49 and 50.
4. Run the backfill against the local Docker DB first, then against Tiger. Refresh the aggregates (`CALL refresh_continuous_aggregate(...)`) and check `prices_hh` has ~35k rows.
5. Optional for the row count on screen: FUELINST (5-minute) adds ~8M rows. Load it last, only if the free service cap allows.

### Tests

- `tests/unit/test_elexon_parse.py`: for each saved sample, `normalise` returns the expected number of rows, no NaN values, UTC tz-aware timestamps, `available_at >= start_time` for every row except forecasts (WINDFOR, NDF), where `available_at < start_time` is allowed and expected.
- `tests/unit/test_elexon_chunks.py`: `chunk_range` over 730 days with 60-day windows yields contiguous, non-overlapping windows covering the full span; 7-day windows never exceed 7 days inclusive.
- `tests/unit/test_mid_rules.py`: zero-volume rows dropped; N2EX rows retained but tagged by series (the aggregate filters them); `available_at` equals `start_time + 30 min + delay`.
- `tests/unit/test_clock_change.py`: the clock-change sample yields 50 distinct `start_time` values for that settlement date and none collide.
- `tests/unit/test_retry.py` (respx): a 429 then 200 sequence results in one successful call and one sleep; five 500s raise.
- `tests/db/test_backfill_idempotent.py`: run `backfill` twice on a 7-day window against Docker; row count unchanged the second time.
- `tests/db/test_aggregates_match_pandas.py`: insert 14 days of synthetic MID rows, refresh, assert `prices_hh` equals a pandas resample to the cent, `prices_daily.spread == max - min` per day, `prices_weekly` rows = 2.

### Exit (Gate 1)

Two years in Tiger for MID, WINDFOR, NDF, INDO, FUELHH, DISEBSP. Aggregates populated. Tell Ernqi and Ayo the row counts and that `prices_hh` is live. Lookahead check: `SELECT count(*) FROM grid_raw WHERE available_at > now()` is 0 for non-forecast datasets.

---

## Phase 2: Live polling and point-in-time features (Gate 3 contribution, ~4 h)

### Tasks

1. `tempo/ingest/poll.py`: every 60 s read `/datasets/metadata/latest`; for each dataset whose `lastUpdated` moved, fetch the last 2 days with the non-stream endpoint and upsert. Also poll MID via `/balancing/pricing/market-index` for the last 2 days. Log one line per fetch. Run it as a `systemd` unit or `nohup` on Ayo's backend box (hand them the unit file).
2. `tempo/features/build.py::build_features(conn, decision_time, horizon=48)`:
   - Target rows: `decision_time + 30 min * k` for `k = 1..48`, aligned to the half hour.
   - Feature columns, each computed from a SQL query with `WHERE available_at <= :decision_time`:
     - `price_lag_1d`, `price_lag_7d`: APX price at the same period 1 and 7 days before the target.
     - `price_last_known`: latest available price at decision time, and `hours_since_last_price`.
     - `daily_spread_lag_1d`, `weekly_mean`, `weekly_std` from the aggregates (aggregates are keyed on `start_time`; add an `available_at` guard by joining to `grid_raw` or by only using buckets fully before `decision_time - 40 min`, document which).
     - `wind_fc`: latest WINDFOR for the target hour published at or before `decision_time`, forward-filled from hourly to half-hourly.
     - `demand_fc`: latest NDF for the target period published at or before `decision_time`.
     - `wind_share_fc = wind_fc / demand_fc`.
     - `hour`, `dow`, `is_weekend`, `period_of_day`.
   - Returns a DataFrame indexed by `target_time` with no NaN in required columns (fill lags with `price_last_known` and set a `lag_missing` flag).
3. `tests/contracts/test_pit_leak.py` (shared, you write it): everyone's point-in-time guarantee.

### Tests

- `tests/db/test_pit_leak.py`: load 30 synthetic days; compute `F1 = build_features(T)`; insert a row with `start_time = T + 1h`, `available_at = T + 1 min`, `value = 9999`; compute `F2`; assert `F1.equals(F2)`. Then insert a row with `available_at = T - 1 min` and assert features changed. Run this for every feature column that reads `grid_raw`.
- `tests/db/test_feature_lags.py`: on synthetic data with the known daily shape, `price_lag_1d` at target `t` equals `prices_hh` at `t - 1 day` exactly; `price_lag_7d` likewise.
- `tests/db/test_wind_interp.py`: hourly WINDFOR values 100 and 200 at 10:00 and 11:00 give `wind_fc` 100 at 10:00 and 10:30 (forward fill) or 150 at 10:30 (interpolate); pick one and assert it.
- `tests/db/test_forecast_versioning.py`: two WINDFOR publications for the same target hour (06:00 publish says 500, 08:00 publish says 700); `build_features(07:00)` uses 500, `build_features(09:00)` uses 700.
- `tests/unit/test_poll.py` (respx + freezegun): unchanged `lastUpdated` triggers no fetch; changed triggers exactly one fetch for that dataset.
- `tests/contracts/test_features_contract.py`: columns match the list above, index is 48 half-hours, dtype float for numeric columns, no NaN in required columns.

### Exit

Poller running on the backend with a log showing fetches. `build_features(now())` returns in under 1 s on Tiger. Leak test green. Hand `build_features` to Ernqi.

---

## Phase 3: Compression and the numbers on screen (Gate 4 contribution, ~2 h)

### Tasks

1. Add a columnstore / compression policy on `grid_raw` for chunks older than 7 days (`ALTER TABLE grid_raw SET (timescaledb.compress, timescaledb.compress_segmentby = 'dataset, series', timescaledb.compress_orderby = 'start_time')` plus `add_compression_policy`). Run it once manually so the stats exist before the demo.
2. `tempo/db/stats.py::storage_stats(conn) -> dict` returning total rows, before and after bytes, and compression ratio from `hypertable_compression_stats`. Ayo renders it.
3. Time the two-year query `SELECT bucket, price FROM prices_hh ORDER BY bucket` on Tiger; it should be well under 1 s. If not, add an index or check the refresh policy.

### Tests

- `tests/db/test_compression_equivalence.py`: load 30 days, snapshot `SELECT * FROM grid_raw ORDER BY 1,2,3,4` to a DataFrame, compress all chunks, re-run the query, assert equal.
- `tests/db/test_storage_stats.py`: `storage_stats` returns ratio > 1 after compression on synthetic data.
- `tests/db/test_two_year_query.py` (marked `slow`): on the full local backfill, the `prices_hh` query completes under 1 s.

### Exit

Stats visible on Ayo's dashboard. Two-year chart instant.

---

## Phase 4: Stretch (only if everything above is green)

- FUELINST 5-minute load for the row count.
- pgvector "similar days": a 48-dim price-shape vector per day in a `day_vectors` table, `nearest_days(date, k)` query. Test: a day's nearest neighbour is itself at distance 0, and on synthetic data even weeks cluster with even weeks.
- Help Ayo with `demo_reset.py` data checks.
