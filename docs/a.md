# Part A: live decisions (Gate 3)

Half of [todo_ernqi.md](todo_ernqi.md). Part B ([b.md](b.md)) is the backtest and honesty side; the two can be worked in parallel. Read "Shared rules" at the bottom before starting.

**Goal:** a trained LightGBM model and `run_decision` writing real 48-period schedules to Tiger every half hour, so the dashboard's Live section shows a real schedule, a forecast band and a hold with its reason, and Ayo has a `decision_id` to click. That is Gate 3, and the most important missing piece for the demo.

## Files you own

Only Part A edits these:

- `tempo/forecast/dataset.py`
- `scripts/train.py`
- `tempo/decide/engine.py`
- `tests/db/test_no_lookahead_training.py`, `tests/db/test_run_decision.py`, `tests/contracts/test_decisions_contract.py` (all new)
- `DbSource.calibration()` in `tempo/dashboard/data.py` (Ayo's file: agree the change with Ayo first)

## To do, in order

1. **`tempo/forecast/dataset.py::make_training_set(conn_or_df, decision_times) -> (X, y)`** (currently a stub). For each historical decision time (every 6 hours over the train window), call `build_features(conn, decision_time)`, add `horizon_k`, and join the realised price for each `target_time` as `y`. Point-in-time correctness comes by construction: features only ever come from `build_features(decision_time)`.
   - Test: `tests/db/test_no_lookahead_training.py`. Build a training set on the local Docker DB, then for every `(decision_time, target_time)` row assert that every feature value equals what `build_features(decision_time)` returns.
2. **`scripts/train.py`** (stub). Train `LightGBMQuantileForecaster` on the last 90 days of Tiger data and save `models/lgbm_{p10,p50,p90}.joblib` with `save()`. Decide where the model lives on the backend box (`/opt/tempo/models/` is gitignored, so either copy it with `scp` or train on the box).
3. **`tempo/decide/engine.py::run_decision(conn, now, forecaster, optimiser, run_id='live')`** (a 4-line stub). The pipeline is `build_features` → `predict` → `plan` → 48 `forecasts` rows + 48 `decisions` rows, returning the first period's `decision_id`. Ayo's side relies on:
   - one batch = 48 rows sharing one `decided_at`
   - `run_id='live'`
   - signed `mw`: + charge, − discharge, 0 hold
   - a non-empty `reason` on every hold
   - `forecast_id` set on every decision
   - Tests: `tests/db/test_run_decision.py` and the shared `tests/contracts/test_decisions_contract.py`.
   - Also fix the one lint error in `engine.py` while you are in there.
4. **Run `run_decision` on Tiger for real**, every half hour if you can, either as a loop on the backend box or with `apscheduler`. Several batches should exist by demo time. Then run `scripts/demo_reset.py` (Ayo's): it ranks replayable live decisions and prints the sentence for each. **Tell Ayo the `decision_id` to click.** That is Gate 3.
5. **Calibration on real forecasts**, once item 4 has produced some. `DbSource.calibration()` is still synthetic. Either agree a shape with Ayo (`nominal`, `observed` columns), or write the reliability table from `tempo.backtest.metrics.calibration()` into a small table. `metrics.py` belongs to Part B: call it, don't edit it.

## Hand-offs

| To | What | When |
|---|---|---|
| Ayo | a `decision_id` to click (`demo_reset` picks one) | after item 4 |
| Ayo | calibration shape | item 5 |
| Girik | any feature you need that `FEATURE_COLUMNS` lacks | now |

## Shared rules (same text in a.md and b.md)

- **Don't change `tempo/forecast/lgbm.py` or `tempo/features/build.py`** without telling the other part. Both parts train the same `LightGBMQuantileForecaster` on `FEATURES = FEATURE_COLUMNS + horizon_k`.
- **`horizon_k`** is `k` in `target_time = decision_time + 30 min * k`, for `k = 1..48`. Both parts must compute it this way, or a model trained by one part predicts wrongly for the other.
- **`run_id='live'`** is only ever written by `run_decision` (Part A). Backtests, training and self-grade use their own ids.
- **Nobody creates Tiger services or forks on demo day.** The free tier holds the primary and the audit's fork only (description.md section 11).
- **Ignore Ayo's rehearsal batch** (`run_id='selftest'`, dated 21 Oct) on Tiger. It is not live data.
- **Tests:** DB tests need the local Docker DB (`bash scripts/dev_db.sh`). On Windows, a test run hangs rather than skipping if Docker isn't running.
- **No known test failures:** the LP failure is fixed (b.md item 1).
