# Ernqi: what is left (as of Sat 24 Oct 2026, evening)

Status check against [ernqi.md](ernqi.md), done by reading main and Tiger, not by asking. Fix anything here that is wrong.

## Done and verified

- Phase 0 and 1: fixture with known answers, `simulate`, cost gate, greedy, perfect foresight, walk-forward, `summary`, `scripts/backtest.py`.
- **Gate 2 reached:** `backtest_results` on Tiger, run `db-20261024T163014Z`, 100 unseen weeks, three strategies, nothing above 100%. Ayo's Honesty tab reads it (it shows the latest `run_id`).
- Phase 2 partly: `PersistenceForecaster`, `LPOptimiser`, `calibration`, `by_regime`, `weak_statements`, and their tests.
- Phase 3 mostly: `self_grade` with `test_selfgrade_known.py`, regime breakdown, weak statements. Ayo's replay simulator now resolves to your `tempo.sim.battery` automatically (the stand-in matched your fixture's known answer to the penny before it was swapped out).

## Girik's build_features has landed

`tempo/features/build.py::build_features(conn, decision_time, horizon=48)` is on main (Sat 24 Oct, evening), with `FEATURE_COLUMNS` and `tests/contracts/test_features_contract.py`. Items 3 and 4 are unblocked.

## To do, in order

1. ~~**Re-run the backtest with regime labels.**~~ Done: run `db-20261024T181359Z`, all 300 rows labelled by wind share of demand (NDF backfilled to the full two years first). Tell Ayo.
2. ~~**`tempo/forecast/lgbm.py::LightGBMQuantileForecaster`**~~ Done, tested on the synthetic fixture (`tests/unit/forecast_frames.py::lgbm_frame`): p50 MAE 4.0 vs persistence 6.1 on 14 unseen days (4.0 is the fixture's noise floor). `FEATURES` is Girik's `FEATURE_COLUMNS` plus `horizon_k`, imported, so it cannot drift. Note: `test_lp_vs_greedy.py::test_lp_schedule_respects_every_constraint` fails on main (hypothesis case `soc0=6e-05` clips 6.4e-05 MWh against a 1e-6 tolerance); fix before task 5.
3. **`tempo/forecast/dataset.py::make_training_set`** and **`tests/db/test_no_lookahead_training.py`** (`build_features` is on main).
4. **`tempo/decide/engine.py::run_decision`** and **`tests/db/test_run_decision.py`** and the shared **`tests/contracts/test_decisions_contract.py`** (`build_features` is on main). This is the single most important missing piece for the demo: without it there are no live decisions, so the Live tab shows an empty schedule and the timing audit has nothing real to click. Ayo's audit expects exactly what ernqi.md says: 48 rows per batch, same `decided_at`, `run_id='live'`, signed `mw`, a `reason` on every hold.
5. **`tempo` and `tempo_lp` strategies in the walk-forward backtest** (task 6) so the Tempo row appears in the honesty table. Retrain per window on train days only.
6. **`scripts/train.py`** (task 8).
7. **Run `run_decision` for real at least once** on Tiger (from a laptop is fine until the backend box exists), then **tell Ayo a `decision_id` worth clicking**. `scripts/demo_reset.py` (Ayo's) will rank candidates for you: it prefers a batch where "as decided" beats every shift and a hold sits nearby. For a convincing demo, several batches over a couple of days are better than one.
8. **Calibration on real forecasts** once `run_decision` has produced some (the `forecasts` table is empty today). The dashboard's calibration chart is still synthetic.
9. **A stored windy-week schedule** for Ayo's Replay tab (ayo.md Phase 3 task 2): one week's `(ts, p10, p50, p90, mw)` that Ayo can animate. Agree the shape with Ayo; a `backtest_results`-style table or a parquet in `models/` both work.
10. **Lint.** Ayo's formatting pass on main fixed most of it; 21 errors are left (`ruff check .`): `tempo/backtest/metrics.py` (7), `walkforward.py` (2), `scripts/backtest.py` (2), `optimise/lp.py`, `sim/battery.py`, `decide/engine.py` (1 each), and the unit tests `test_backtest_synthetic.py` (3), `test_selfgrade_known.py` (2), `test_metrics_summary.py`, `test_walkforward_windows.py` (1 each). Mostly long lines and `zip(strict=)`.
11. **Gate line:** write the Gate 2 date at the top of ernqi.md.

## Hand-offs

| To | What | When |
|---|---|---|
| Ayo | a `decision_id` to click, with a hold nearby | after item 7 |
| Ayo | regime-labelled backtest run | after item 1 |
| Ayo | windy-week schedule for Replay | after item 9 |
| Girik | which NDF/WINDFOR columns `build_features` must expose for LightGBM | now |

## Rules for demo day

- Nobody creates Tiger services or forks on demo day. The free tier holds two services: the primary and the audit's fork. See description.md section 11.
- `run_id='live'` is sacred: backtests, training and self-grade write under their own ids (`self_grade` already does).
