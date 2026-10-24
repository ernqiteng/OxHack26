# If there is time

Work that is planned but **not built**. Nothing in this file exists in the code yet, and no other doc should describe it as done. Move an item out of here only when it is built, tested and deployed.

## 1. Parallel walk-forward backtest on the Vultr workers, with a measured speed-up

**Status: not started.** Today `scripts/backtest.py` runs all 100 test windows in one process on one machine, in about 7 minutes on a laptop.

**Why it fits.** The 100 windows are independent (each trains its own LightGBM model on its own train days), so they split across workers with no coordination. The backtest is single-threaded throughout (LightGBM runs with one thread for determinism), so the laptop's 7 minutes is already a one-core time.

**Expected result.** A 1-vCPU worker (`vc2-1c-1gb`) will probably take 10 to 14 minutes for all 100 windows on its own. Five workers would take roughly 3 minutes each, plus loading their data, so a speed-up of about 3.5 to 4.5x against one worker. This is an estimate, not a measurement.

**Plan.**

1. `tempo/backtest/features.py::load_frames(conn, start, end)`: load only a date range. Loading all two years takes about 600 MB, too close to a worker's 1 GB; one worker's 20 windows need about six months, roughly 150 MB.
2. `POST /backtest {database_url, windows, strategies, run_id}` in `tempo/worker/main.py`, next to `/replay`. It loads the range its windows need (from about 10 days before the earliest train start to the latest test end), runs `run_strategy` for those windows, and returns the rows. It must not change `/replay`.
3. `scripts/backtest.py --workers 5`: split the windows into five chunks, send them through `HttpWorkerPool` (reusing its busy/idle tags), gather the rows, and write them once with a new `run_id`.
4. Equivalence test, like `tests/db/test_fork_equals_inprocess.py`: the parallel run's rows must equal the sequential run's exactly (LightGBM is deterministic), using `LocalWorkerPool`.
5. Measure honestly: time the same windows on one worker and on five workers of the same plan, and store both times with the run. Do not compare five workers against a multi-core laptop.
6. Only then may description.md sections 5 and 10 say "parallel walk-forward backtests with a measured speed-up of N x", with the measured N.

**Blockers and risks.**

- The Vultr account belongs to Ayo, and the `.env` on Ernqi's laptop has no `VULTR_API_KEY`: Ayo has to deploy.
- The workers are created from a snapshot, so new worker code means rebuilding the snapshot and the pool. The same five workers run the timing audit, so deploy only after the audit has been rehearsed, and never on demo day.
- A running backtest must mark workers busy so that an audit click cannot land on a busy worker.

**Effort.** About 3 to 4 hours, most of it locally testable before any deploy.

## 2. Battery-size sweep

**Status: not started.** description.md lists it as a nice-to-have. Re-run the backtest for capacity in {1, 2, 4, 8} MWh at 1 MW and show a table. Test: perfect-foresight PnL never falls as capacity grows. It reuses the endpoint from item 1, so build it after that.
