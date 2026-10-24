# Part B: backtest, replay and clean-up

Half of [todo_ernqi.md](todo_ernqi.md). Part A ([a.md](a.md)) is the live decision engine; the two can be worked in parallel. Read "Shared rules" at the bottom before starting.

**Goal:** a Tempo row in the honesty table. The dashboard's ladder, header number and hero sentence switch to it automatically, because they prefer a strategy whose name starts with "tempo". Also a real replay week for Ayo, and `make lint` green.

## Files you own

Only Part B edits these:

- `tempo/backtest/` (`walkforward.py`, `metrics.py`, and a new `features.py` if you write one)
- `scripts/backtest.py`
- `tempo/optimise/lp.py`, `tempo/optimise/greedy.py`, `tempo/sim/battery.py`
- `tests/unit/forecast_frames.py` and the backtest, metrics and LP unit tests
- `DbSource.replay_week()` in `tempo/dashboard/data.py` (Ayo's file: agree the change with Ayo first)
- `docs/ernqi.md`

## To do, in order

1. ~~**Fix the failing LP test.**~~ Done. It was a real bug in `lp.py`, not a strict tolerance. The LP sold the 6e-5 MWh it started with (0.1 kW), then charged to exactly full; zeroing flows under `TINY_MW` dropped that sale, so the full charge overfilled the battery. `_executable()` now trims each period to what the battery can do after zeroing. Regression test: `test_zeroing_a_tiny_sale_does_not_overfill`. Full suite green (390/390).
2. ~~**`tempo` and `tempo_lp` strategies in the walk-forward backtest.**~~ Done. Run **`db-20261024T202144Z`** on Tiger (500 rows, the latest run, so the dashboard shows the Tempo row): over 100 unseen weeks, **tempo 66.4% of perfect, tempo_lp 68.3%**, persistence + greedy 52.9%, simple rule 33.1%. No week above 100% (tempo's best is 90.2%), tempo never loses money in a week (worst 31.2%), and tempo_lp beats persistence in 81 of 100 weeks. Windy vs calm (total PnL over total perfect, as the dashboard computes it): tempo_lp 69.0% vs 67.4%, tempo 65.8% vs 67.3%.
   - Features: `tempo/backtest/features.py` answers `build_features`' own SQL from frames loaded once (`FrameConn`), so the backtest runs Girik's `build_features` unchanged. `tests/db/test_backtest_features.py` checks it against the real database on two synthetic markets; three deliberate leaks each make it fail.
   - `TempoModel` trains per window every 6 h over the train days, on targets before `test_start` only, and plans each UK test day a minute before its first period. `scripts/backtest.py --no-tempo` skips it. A full run takes about 7 minutes.
   - **Tell Girik:** `build_features` raised `TypeError` instead of its "no ... published" `ValueError` when a decision's window had no WINDFOR/NDF rows at all (an empty Series without a DatetimeIndex). Fixed in `build.py` with `_forecast_series()`; regression test in `tests/db/test_backtest_features.py`.
3. ~~**Replay week for Ayo.**~~ Done. `models/replay_week.parquet` (+ `.json`): the windy week of **2026-06-11**, chosen as the median windy week for tempo in `db-20261024T202144Z` (62.9% of perfect, GBP 611.32), not the best. Same columns as the synthetic week. `scripts/replay_week.py` rebuilds it and refuses to write unless the final cumulative PnL matches the backtest's `pnl_gbp` for that week. `DbSource.replay_week()` now reads it (a small change in Ayo's `data.py`: tell Ayo) and falls back to synthetic with a note if the file is missing.
4. ~~**Lint.**~~ Done. `ruff check .` and `ruff format --check .` are clean on the whole repo (Ayo's `engine.py` rewrite cleared the last Part A error). f-strings were split so every printed sentence is unchanged.
5. ~~**Housekeeping.**~~ Already done by others: the Gate 2 date is at the top of ernqi.md, and `scratch_seen.txt` is gone from main.

Also fixed along the way: `test_lp_at_least_greedy_on_p50` failed on a new hypothesis case (flat 339 GBP/MWh, 3.2e-6 MWh stored: greedy sold the sliver for 0.1p, the LP refuses sub-kW trades by design). Its tolerance is now sized from `TINY_MW`.

**State:** full suite 463 passed, 3 skipped (Girik's two-year query tests need a full local backfill DB).

## Hand-offs

| To | What | When |
|---|---|---|
| Ayo | new `run_id` with the Tempo row: `db-20261024T202144Z` (latest, picked up automatically) | done |
| Ayo | replay week: `models/replay_week.parquet`, read by `DbSource.replay_week()` | done |

## Shared rules (same text in a.md and b.md)

- **Don't change `tempo/forecast/lgbm.py` or `tempo/features/build.py`** without telling the other part. Both parts train the same `LightGBMQuantileForecaster` on `FEATURES = FEATURE_COLUMNS + horizon_k`.
- **`horizon_k`** is `k` in `target_time = decision_time + 30 min * k`, for `k = 1..48`. Both parts must compute it this way, or a model trained by one part predicts wrongly for the other.
- **`run_id='live'`** is only ever written by `run_decision` (Part A). Backtests, training and self-grade use their own ids.
- **Nobody creates Tiger services or forks on demo day.** The free tier holds the primary and the audit's fork only (description.md section 11).
- **Ignore Ayo's rehearsal batch** (`run_id='selftest'`, dated 21 Oct) on Tiger. It is not live data.
- **Tests:** DB tests need the local Docker DB (`bash scripts/dev_db.sh`). On Windows, a test run hangs rather than skipping if Docker isn't running.
- **No known test failures:** the LP failure is fixed (b.md item 1).
