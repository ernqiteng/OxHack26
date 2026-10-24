# Ernqi: what is left (updated Sat 24 Oct 2026, late evening)

Checked against `ayo` after merging your branch (all 203 unit/contract/DB tests green) and against Tiger. Fix anything here that is wrong.

## Done

- Phase 0 and 1: fixture, `simulate`, cost gate, greedy, perfect foresight, walk-forward, `summary`, `scripts/backtest.py`. **Gate 2 reached.**
- Backtest on Tiger with regime labels: run `db-20261024T181359Z`, 300 rows, all labelled (NDF is now backfilled for the full two years, 2.06M rows). Superseded by **`db-20261024T202144Z`** (500 rows, adds `tempo` and `tempo_lp`), which is the latest run and the one the dashboard's Honesty section shows.
- Part A and Part B are both done (a.md, b.md): Gate 3 reached, demo decision #1353.
- `LightGBMQuantileForecaster` with `save`/`load`, `FEATURES = FEATURE_COLUMNS + horizon_k`, `test_quantile_order.py`, `test_lgbm_beats_persistence.py` (p50 MAE 4.0 vs 6.1 on unseen synthetic days).
- `PersistenceForecaster`, `LPOptimiser`, `calibration`, `by_regime`, `weak_statements`, `self_grade` and their tests. Ayo's dashboard already calls `self_grade` and `weak_statements`.

## Nothing is blocking you now

`build_features` and `FEATURE_COLUMNS` are on main, prices on Tiger are live to the half hour (Girik's poller runs on the backend box), NDF is complete. Everything below was yours to finish and is now done; what is left is optional and listed in [time.md](time.md).

## To do: split into two independent parts

The remaining work is split so that two people can work in parallel without editing the same files. Each part lists the files it owns, its tasks in order, and its hand-offs.

- **[a.md](a.md): live decisions (Gate 3).** `make_training_set`, `scripts/train.py`, `run_decision`, running it on Tiger, the `decision_id` for Ayo, and calibration on real forecasts.
- **[b.md](b.md): backtest, replay and clean-up.** The failing LP test, the `tempo`/`tempo_lp` backtest strategies, the replay week for Ayo, lint, and housekeeping.

Both share `tempo/forecast/lgbm.py`, `FEATURE_COLUMNS` and one definition of `horizon_k`; the shared rules are at the bottom of each part.

## Rules for demo day

- Nobody creates Tiger services or forks on demo day: the free tier holds the primary and the audit's fork only (description.md section 11).
- `run_id='live'` is only ever written by `run_decision`. Backtests, training and self-grade use their own ids.
- Ayo's rehearsal batch (`run_id='selftest'`, dated 21 Oct) has been removed from Tiger (0 rows on 24 Oct evening). If it reappears, ignore it: it is not live data.
