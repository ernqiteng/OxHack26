# Girik: what is left (as of Sat 24 Oct 2026, evening)

Status check against [girik.md](girik.md), first written by Ayo from main and Tiger, then corrected by Girik against main and Tiger (same evening). Fix anything here that is wrong.

> **Status (checked against main and Tiger, 25 Oct 2026 00:30 BST): every item below is done.** NDF is backfilled for the full two years (2.06M rows), `prices_daily` has 732 rows and `prices_weekly` 105, `build_features` is on main, the poller runs on the backend box (newest price 24 Oct 23:00 UTC at the check), and every test named in items 4 to 9 exists, including `ingest_log` in `tests/conftest.py`. Gates 0, 1, 3 and 4 are recorded at the top of girik.md. The list is kept for reference; the counts in "Done and verified" are from the time it was written.

## Done and verified on Tiger

- Phase 0: schema with the three hierarchical aggregates, `conn.py`, local Docker DB, `test_schema.py`.
- Phase 1: Elexon client, `normalise`, resumable two-year backfill (resume reads `ingest_log`, coverage checked per dataset). Tiger `grid_raw` holds MID 70k, WINDFOR 426k, FUELHH 701k, INDO 35k, DISEBSP 35k rows, 24 Oct 2024 to 24 Oct 2026, and NDF 676k rows for 24 Oct 2024 to 22 Jun 2025 only (see item 1; since completed: 2.06M rows to 26 Oct 2026). `prices_hh` has 35,018 half-hours (35,064 on 25 Oct, growing with the poller). Gate 1 lookahead check on Tiger: **0** non-forecast rows with `available_at > now()`.
- Storage: the cap is enforced on Tiger's API `metrics.storage_mb`, which is **533 of 750 MB** now (it includes Tiger's ~340 MB own overhead). `pg_database_size` (~150 MB) does not include that overhead; don't use it for headroom. Headroom is ~217 MB.
- Phase 3, early: compression policy is on `grid_raw` (107 chunks, 105 compressed), `storage_stats()` exists, `test_compression_equivalence.py` passes and already asserts `storage_stats` ratio > 1 after compression.
- Ernqi's real-data backtest runs on your `prices_hh` (Gate 2 reached).
- Ayo fixed the four `test_fork_equals_inprocess` tests that broke once `prices_hh` became a continuous aggregate (they now insert into `grid_raw` and refresh).

## You are on the critical path

Ernqi cannot write `run_decision` (the live decisions) until `build_features` exists, and Ayo cannot audit a real decision until Ernqi has one. **Hand `build_features` over the moment the contract test passes, even before the leak tests are finished.** Item 1 goes first only because it takes ~15 minutes and then runs unattended, and `build_features` on Tiger needs its output (current `demand_fc` and the daily and weekly aggregates).

## To do, in order

1. **Fix the loader, then resume the NDF backfill.** NDF stopped at 21 Jun 2025 (4 of 13 windows in `ingest_log`). This was a deliberate pause, not a crash (recorded in needs.md B2): the loader only compressed after a whole dataset, so the 9 remaining windows (~1.4M rows) would have sat uncompressed and could push Tiger past 750 MB, which turns it read-only for everyone. **Do not just re-run it.** First:
   - compress, reindex and vacuum after **every window**, so at most one window (~160k rows) is ever uncompressed;
   - make `--max-storage-mb` read Tiger's `metrics.storage_mb` from the API before each window (not `pg_database_size`), and run with `--max-storage-mb 680`;
   - test both (with a mutation check), then resume; `ingest_log` skips the 4 finished windows.

   The missing part is the **recent** 16 months, which is what Ernqi trains on (last 90 days) and what live decisions need for `demand_fc` and the regime label. Tell Ernqi when it lands. Expected end state ~560 to 600 MB of 750.
2. **Refresh the daily and weekly aggregates on Tiger.** `prices_daily` has 4 rows and `prices_weekly` 1 row on Tiger (only `prices_hh` was refreshed by hand), so `daily_spread_lag_1d`, `weekly_mean` and `weekly_std` would read nothing. The resumed backfill ends with a full two-year refresh of all three (parents first); if item 1 is delayed, run `CALL refresh_continuous_aggregate(...)` for `prices_hh`, `prices_daily`, `prices_weekly` in that order over the full range. The refresh policies only cover the last few days, so do the same after any backfill that touches older rows.
3. **`tempo/features/build.py::build_features(conn, decision_time, horizon=48)`** (Phase 2 task 2). Still a 4-line stub. Columns and rules are in girik.md Phase 2. Decided:
   - **WINDFOR hourly → half-hourly: forward-fill** (interpolation needs the next hour's forecast, which may not be published at decision time).
   - **Aggregate point-in-time guard: Option A**, only buckets with start ≤ `decision_time − (30 + MID_AVAILABILITY_DELAY_MIN)` min (= −40 min today), and only days or weeks that are complete under that cutoff. This is only equivalent to the `available_at` rule because MID's `available_at` is always `start + 30 + delay`, so `build_features` must refuse to run if the stored MID offset differs from the configured delay.
   - **NDF full history** (confirmed with Ernqi after the 65.5 MiB local load).

   Hand to Ernqi as soon as `tests/contracts/test_features_contract.py` is green.
4. **`tests/contracts/test_features_contract.py`** and **`tests/contracts/test_pit_leak.py`** (shared, yours). The leak test is the one HRT judges would ask about: insert a row with `available_at` after the decision time, features must not change; insert one before, features must change. Run it for **every feature column that reads `grid_raw`**, and show the **mutation check**: remove the point-in-time filter from each query in turn and show `test_pit_leak` failing each time. A version that passes against a leaking query is worse than no test.
5. **Option A vs Option B equivalence test** on real MID data (the saved Elexon sample, including the 26 Oct 2025 clock change): compare `build_features`' aggregate cutoff against an actual join to `grid_raw` on `available_at <= decision_time` across many decision times. It must **fail if `MID_AVAILABILITY_DELAY_MIN` changes** without the data being reloaded, so a leak cannot hide behind an edited constant.
6. **`tests/db/test_feature_lags.py`, `test_wind_interp.py` (forward-fill), `test_forecast_versioning.py`** (Phase 2 tests).
7. **`tempo/ingest/poll.py` + `scripts/poll.py`** (Phase 2 task 1) and **`tests/unit/test_poll.py`**. All six datasets (MID included) are in `/datasets/metadata/latest`, so the poller is metadata-driven. **NDF's non-stream endpoint rejects publish windows over 1 day** (verified): split NDF into 1-day calls or use `/datasets/NDF/stream`. The newest price on Tiger is 24 Oct 00:00 UTC, so the Live tab is a day stale. Ayo's `deploy/systemd/tempo-poller.service` already runs `scripts/poll.py` (no second unit file). Ayo's backend box does not exist yet; until it does, run the poller with `nohup` from a laptop that stays on, so there is fresh data in the demo. Clocks go back on Sun 25 Oct, so the poller sees a real 50-period day live.
8. **Phase 3 leftovers:** `tests/db/test_two_year_query.py` (slow marker) and the measured two-year query time written into needs.md. `storage_stats` is already tested in `test_compression_equivalence.py`; split it into `tests/db/test_storage_stats.py` only to match girik.md's file name. Ayo's Honesty tab already calls `storage_stats(conn)` and shows "X rows, compressed Y%".
9. **Housekeeping:** `tests/conftest.py` truncates a fixed table list that predates `ingest_log` (your `helpers.clean` works around it). Adding `ingest_log` there needs an OK first: `conftest.py` is shared. `schema.sql` is the single source of truth and the aggregate definitions are already in it on main.
10. **Gate lines:** write the Gate 0 date at the top of girik.md now. Gate 1 needs all six datasets for two years on Tiger, so write it after item 1.

## Hand-offs

| To | What | When |
|---|---|---|
| Ernqi | `build_features` | the moment the contract test is green |
| Ernqi | WINDFOR is loaded, re-run the backtest for regime labels | now for WINDFOR; NDF and the daily and weekly aggregates after items 1 and 2 |
| Ayo | poller `systemd` unit is already in `deploy/systemd/tempo-poller.service`; `scripts/poll.py` is the entry point | with item 7 |
| Ayo | two-year query timing and row count for the storage line | with item 8 |

## Rules for demo day

- Nobody creates Tiger services or forks on demo day. The free tier holds two services: the primary and the audit's fork. See description.md section 11.
- `prices_hh` must be fresh at demo time: poller running, and the refresh policy covers the last 3 days.
- Watch `metrics.storage_mb`, not `pg_database_size`: the service goes read-only at 750 MB.
