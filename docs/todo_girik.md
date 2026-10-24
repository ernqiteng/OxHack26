# Girik: what is left (as of Sat 24 Oct 2026, evening)

Status check against [girik.md](girik.md), done by reading main and Tiger, not by asking. Fix anything here that is wrong.

## Done and verified on Tiger

- Phase 0: schema with the three hierarchical aggregates, `conn.py`, local Docker DB, `test_schema.py`.
- Phase 1: Elexon client, `normalise`, resumable two-year backfill. Tiger `grid_raw` holds MID 70k, WINDFOR 426k, FUELHH 701k, INDO 35k, DISEBSP 35k rows, 24 Oct 2024 to 24 Oct 2026. `prices_hh` has 35,018 half-hours. Database is 154 MB (cap 750 MiB).
- Phase 3, early: compression policy is on `grid_raw` (107 chunks, 105 compressed), `storage_stats()` exists, `test_compression_equivalence.py` passes.
- Ernqi's real-data backtest runs on your `prices_hh` (Gate 2 reached).

## You are on the critical path

Ernqi cannot write `run_decision` (the live decisions) until `build_features` exists, and Ayo cannot audit a real decision until Ernqi has one. Nothing else on the team is blocked by anything but this. **Do task 1 first and hand it over the moment the contract test passes, even before the leak tests are finished.**

## To do, in order

1. **`tempo/features/build.py::build_features(conn, decision_time, horizon=48)`** (Phase 2 task 2). Still a 4-line stub. Columns and rules are in girik.md Phase 2. Hand to Ernqi as soon as `tests/contracts/test_features_contract.py` is green.
2. **`tests/contracts/test_features_contract.py`** and **`tests/contracts/test_pit_leak.py`** (shared, yours). The leak test is the one HRT judges would ask about: insert a row with `available_at` after the decision time, features must not change.
3. **`tests/db/test_feature_lags.py`, `test_wind_interp.py`, `test_forecast_versioning.py`** (Phase 2 tests).
4. **NDF backfill stopped at 21 Jun 2025** (4 windows in `ingest_log`, the other datasets have 13 and reach Oct 2026). If that was deliberate for storage, write it in needs.md B2 and tell Ernqi, because `demand_fc` will be NULL for the last 16 months and the regime label needs it. If it was a crash, resume it: the database has ~250 MB of headroom before the 750 MiB cap (339 MB of that cap is Tiger's own overhead).
5. **`tempo/ingest/poll.py` + `scripts/poll.py`** (Phase 2 task 1) and **`tests/unit/test_poll.py`**. The newest price on Tiger is 24 Oct 00:00 UTC, so the Live tab is a day stale. Ayo's backend box does not exist yet (waiting on Vultr); until it does, run the poller with `nohup` from a laptop that stays on, so there is fresh data in the demo.
6. **`prices_hh` history refresh.** The refresh policy only covers the last 3 days. After any backfill that touches older rows, run `CALL refresh_continuous_aggregate('prices_hh', NULL, now() - interval '30 minutes')` (Ernqi had to do this once already) and then `prices_daily`, `prices_weekly`.
7. **Phase 3 leftovers:** `tests/db/test_storage_stats.py`, `tests/db/test_two_year_query.py` (slow marker), and the measured two-year query time written into needs.md. Ayo's Honesty tab already calls `storage_stats(conn)` and shows "X rows, compressed Y%".
8. **Housekeeping:** `tests/conftest.py` truncates a fixed table list that predates `ingest_log` (your `helpers.clean` works around it). Add `ingest_log` there. Commit the aggregate definitions you already have (they are in `schema.sql` on main now, good) and keep `schema.sql` the single source of truth.
9. **Gate line:** write the Gate 1 date at the top of girik.md.

## Hand-offs

| To | What | When |
|---|---|---|
| Ernqi | `build_features` | the moment the contract test is green |
| Ernqi | WINDFOR and NDF are loaded, re-run the backtest for regime labels | now for WINDFOR; NDF after item 4 |
| Ayo | poller `systemd` unit is already in `deploy/systemd/tempo-poller.service`; confirm `scripts/poll.py` is the entry point | with item 5 |
| Ayo | two-year query timing and row count for the storage line | with item 7 |

## Rules for demo day

- Nobody creates Tiger services or forks on demo day. The free tier holds two services: the primary and the audit's fork. See description.md section 11.
- `prices_hh` must be fresh at demo time: poller running, and the refresh policy covers the last 3 days.
