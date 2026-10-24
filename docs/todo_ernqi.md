# Ernqi: what is left (updated Sat 24 Oct 2026, late evening)

Checked against `ayo` after merging your branch (all 203 unit/contract/DB tests green) and against Tiger. Fix anything here that is wrong.

## Done

- Phase 0 and 1: fixture, `simulate`, cost gate, greedy, perfect foresight, walk-forward, `summary`, `scripts/backtest.py`. **Gate 2 reached.**
- Backtest on Tiger with regime labels: run `db-20261024T181359Z`, 300 rows, all labelled (NDF is now backfilled for the full two years, 2.06M rows). The dashboard's Honesty section reads the latest run, so the regime chart is real now.
- `LightGBMQuantileForecaster` with `save`/`load`, `FEATURES = FEATURE_COLUMNS + horizon_k`, `test_quantile_order.py`, `test_lgbm_beats_persistence.py` (p50 MAE 4.0 vs 6.1 on unseen synthetic days).
- `PersistenceForecaster`, `LPOptimiser`, `calibration`, `by_regime`, `weak_statements`, `self_grade` and their tests. Ayo's dashboard already calls `self_grade` and `weak_statements`.

## Nothing is blocking you now

`build_features` and `FEATURE_COLUMNS` are on main, prices on Tiger are live to the half hour (Girik's poller runs on the backend box), NDF is complete. Everything below is yours to finish, and item 1 is the last thing between the team and Gate 3.

## To do, in order

1. **`tempo/decide/engine.py::run_decision(conn, now, forecaster, optimiser, run_id='live')`** (still a 4-line stub). `build_features` → `predict` → `plan` → 48 `forecasts` rows + 48 `decisions` rows, return the first period's `decision_id`. What Ayo's side relies on: one batch = 48 rows sharing one `decided_at`, `run_id='live'`, signed `mw` (+ charge, − discharge, 0 hold), a non-empty `reason` on every hold, `forecast_id` set. Tests: `tests/db/test_run_decision.py` and the shared `tests/contracts/test_decisions_contract.py`.
2. **`tempo/forecast/dataset.py::make_training_set(conn_or_df, decision_times) -> (X, y)`** (stub) with `horizon_k`, plus `tests/db/test_no_lookahead_training.py`. `run_decision` needs a trained model, so this and item 1 go together.
3. **`scripts/train.py`** (stub): train on the last 90 days of Tiger data, save `models/lgbm_{p10,p50,p90}.joblib`. Decide where the model lives on the backend box (`/opt/tempo/models/`, gitignored, so copy it with `scp` or train on the box).
4. **Run `run_decision` on Tiger for real**, every half hour if you can (a loop on the backend box or `apscheduler`), so the Live section shows a schedule, the forecast band and a real hold with its reason, and so several batches exist by demo time. Then run `scripts/demo_reset.py` (Ayo's): it ranks replayable live decisions and prints the sentence for each. **Tell Ayo the `decision_id` to click.** That is Gate 3.
5. **Tempo row in the backtest.** `walkforward.STRATEGIES` still has only `simple_rule` and `persistence_greedy`; add `tempo` (LightGBM + greedy) and `tempo_lp`, retrained per window on train days only, and re-run `scripts/backtest.py --source db --write` with a new `run_id`. The ladder, the header number and the hero sentence on the dashboard switch to the Tempo row automatically (they prefer a strategy whose name starts with "tempo").
6. **Calibration on real forecasts** once item 4 has produced some: `DbSource.calibration()` in `tempo/dashboard/data.py` is still synthetic; agree a shape with Ayo (`nominal`, `observed` columns) or write the reliability table to a small table.
7. **Replay week for Ayo** (ayo.md Phase 3 task 2): one windy week's `(ts, actual, p10, p50, p90, mw, soc_mwh, cum_pnl_gbp)` at 48 rows/day. A parquet in `models/` or a query Ayo can run both work; `DbSource.replay_week()` is the hook.
8. **Lint.** 21 errors left on `ruff check .`, all yours: `tempo/backtest/metrics.py` (7), `tests/unit/test_backtest_synthetic.py` (3), `tests/unit/test_selfgrade_known.py` (2), `walkforward.py` (2), `scripts/backtest.py` (2), one each in `test_walkforward_windows.py`, `test_metrics_summary.py`, `sim/battery.py`, `optimise/lp.py`, `decide/engine.py`; plus `ruff format` wants to reformat 2 files. `ruff check . --fix && ruff format .` clears most of it. The pre-push hook (`make lint`) stays red until then.
9. **Housekeeping:** delete the empty `scratch_seen.txt` that came in with commit `3aea766`; write the Gate 2 date at the top of ernqi.md.

## Hand-offs

| To | What | When |
|---|---|---|
| Ayo | a `decision_id` to click (demo_reset picks one) | after item 4 |
| Ayo | calibration shape, replay week | items 6 and 7 |
| Girik | any feature you need that `FEATURE_COLUMNS` lacks | now |

## Rules for demo day

- Nobody creates Tiger services or forks on demo day: the free tier holds the primary and the audit's fork only (description.md section 11).
- `run_id='live'` is only ever written by `run_decision`. Backtests, training and self-grade use their own ids.
- Ayo's rehearsal batch (`run_id='selftest'`, dated 21 Oct) exists on Tiger until the demo; ignore it, it is not live data.
