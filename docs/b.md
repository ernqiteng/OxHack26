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
2. **`tempo` and `tempo_lp` strategies in the walk-forward backtest.** `walkforward.STRATEGIES` has only `simple_rule`, `persistence_greedy` and `perfect`. Add:
   - `tempo` (LightGBM + greedy)
   - `tempo_lp` (LightGBM + LP)

   Both retrain per window on that window's train days only.
   - Features: calling `build_features` on Tiger for every decision time in 100 windows would take hours, so build the same `FEATURE_COLUMNS` in memory from `prices_hh` + `grid_raw` frames (for example in `tempo/backtest/features.py`). Respect the same point-in-time rules as `build_features`: forecasts with `available_at <= decision_time`, and prices only once `bucket + 40 min <= decision_time`. Prove it with a DB test showing your frame equals `build_features` on the local DB for a few decision times.
   - Re-run `scripts/backtest.py --source db --write` with a new `run_id`. Check that no week beats perfect: one that does means a lookahead leak.
3. **Replay week for Ayo** (ayo.md Phase 3 task 2): one windy week's `(ts, actual, p10, p50, p90, mw, soc_mwh, cum_pnl_gbp)` at 48 rows a day, taken from the `tempo` strategy in item 2. A parquet in `models/` or a query Ayo can run both work; `DbSource.replay_week()` is the hook (synthetic today). Agree the shape with Ayo.
4. **Lint.** `ruff check .` has 20 errors in Part B's files:
   - `tempo/backtest/metrics.py` (7)
   - `tests/unit/test_backtest_synthetic.py` (3)
   - `tests/unit/test_selfgrade_known.py` (2)
   - `walkforward.py` (2)
   - `scripts/backtest.py` (2)
   - one each in `test_walkforward_windows.py`, `test_metrics_summary.py`, `sim/battery.py` and `optimise/lp.py`

   `ruff format` also wants to reformat `walkforward.py` and `tests/unit/forecast_frames.py`. `ruff check . --fix && ruff format .` clears most of it. The pre-push hook (`make lint`) stays red until this is done, plus Part A's one error in `engine.py`.
5. **Housekeeping:**
   - Write the Gate 2 date (Sat 24 Oct 2026) at the top of ernqi.md.
   - `scratch_seen.txt` is already deleted on `ernqi`; it disappears from main at the next merge.

## Hand-offs

| To | What | When |
|---|---|---|
| Ayo | new `run_id` with the Tempo row | after item 2 |
| Ayo | replay week shape and data | item 3 |

## Shared rules (same text in a.md and b.md)

- **Don't change `tempo/forecast/lgbm.py` or `tempo/features/build.py`** without telling the other part. Both parts train the same `LightGBMQuantileForecaster` on `FEATURES = FEATURE_COLUMNS + horizon_k`.
- **`horizon_k`** is `k` in `target_time = decision_time + 30 min * k`, for `k = 1..48`. Both parts must compute it this way, or a model trained by one part predicts wrongly for the other.
- **`run_id='live'`** is only ever written by `run_decision` (Part A). Backtests, training and self-grade use their own ids.
- **Nobody creates Tiger services or forks on demo day.** The free tier holds the primary and the audit's fork only (description.md section 11).
- **Ignore Ayo's rehearsal batch** (`run_id='selftest'`, dated 21 Oct) on Tiger. It is not live data.
- **Tests:** DB tests need the local Docker DB (`bash scripts/dev_db.sh`). On Windows, a test run hangs rather than skipping if Docker isn't running.
- **No known test failures:** the LP failure is fixed (b.md item 1).
