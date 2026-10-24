# Part B: Brain (Ernqi)

Gate reached: _(write date/time here as you pass each gate)_

You own the battery, the optimiser, the forecaster, the walk-forward backtest and every honesty metric. Everything you produce is a number that a judge will read, so every number has a known-answer test behind it.

**You own:** `tempo/sim/`, `tempo/forecast/`, `tempo/optimise/`, `tempo/backtest/`, `tempo/decide/`, `tests/fixtures/synthetic.py`, `scripts/train.py`, `scripts/backtest.py`.

**You depend on:** Ayo's `prices_hh` on Tiger (Phase 1 exit) and `build_features` (Phase 2 exit). Until those land you work entirely on the synthetic fixture, which you write first, so you are never blocked.

**Others depend on you for:** `make_synthetic_market` (everyone, Phase 0), `Battery` and `simulate` (Girik's replay and worker, Phase 1), `decisions` rows (Girik's audit and dashboard, Phase 2), `backtest_results` (Girik's honesty panel, Phase 1 exit).

Battery parameters and the price-series decision are in [description.md](description.md) section 3 and [needs.md](needs.md) section A3.

---

## Phase 0: Synthetic market and battery stub (~90 min)

### Tasks

1. `tests/fixtures/synthetic.py::make_synthetic_market(days=60, seed=0, start=datetime(2026,1,5,tz=UTC)) -> DataFrame` in `grid_raw` long format (see plan.md 2.3). Components:
   - Base price `60 + 40 * shape(period)` where `shape` is low from 01:00 to 05:00 and high from 17:00 to 19:00.
   - Even ISO weeks are "windy": night prices drop by 30 and `WINDFOR` is high.
   - Weekend evenings 15 lower.
   - Noise `N(0, 5)` from a seeded generator.
   - `NDF` demand tracks the evening peak.
   - `available_at` as plan.md 2.3 describes.
2. Compute and hard-code in the docstring: 7-day perfect-foresight profit with the default battery, 7-day simple-rule profit, both to 0.1 £. You will compute these once your sim exists; update the docstring then and add the assertion.
3. `tempo/sim/battery.py`: `Battery` dataclass with the defaults from plan.md 2.2. Stub `simulate` that raises `NotImplementedError` so the contract test exists from day one.

### Tests

- `tests/unit/test_synthetic.py`: two calls with the same seed are identical; 60 days produce `60 * 48` MID rows; the mean 03:00 price is lower than the mean 18:00 price; even weeks have lower night prices than odd weeks.
- `tests/contracts/test_battery_contract.py`: `Battery()` has the agreed defaults; `simulate` signature matches plan.md.

### Exit

Fixture merged to `main`. Girik and Ayo can import it.

---

## Phase 1: Battery, optimiser, backtest harness (Gate 2, ~5 h)

### Tasks

1. `tempo/sim/battery.py::simulate(battery, schedule_mw, prices) -> SimResult`:
   - `schedule_mw[k]` is the power for period `k`: positive = charge (buy), negative = discharge (sell), clipped to `±power_mw`.
   - Energy per period = `mw * 0.5` MWh. Charging adds `energy * sqrt(eff)` to SoC; discharging removes `energy / sqrt(eff)` from SoC (split round-trip efficiency symmetrically, document this).
   - SoC clipped to `[0, capacity]`; any clipped energy is not bought or sold (the schedule is infeasible there and the sim reports `clipped_mwh`).
   - PnL per period = `-mw * 0.5 * price` (buying costs, selling earns).
   - Cycles = total discharged MWh / capacity. `cycle_cost = cycles * cycle_cost_gbp` subtracted from PnL.
   - `SimResult`: `pnl_gbp`, `gross_pnl_gbp`, `cycle_cost_gbp`, `soc_path`, `cycles`, `clipped_mwh`.
2. `tempo/optimise/gate.py::cost_gate(buy_price, sell_price, battery) -> (ok, expected_spread, reason)`: ok iff `sell * sqrt(eff) * sqrt(eff) - buy > cycle_cost_per_mwh`. Reason strings are human-readable, e.g. `"spread 11.2 < cost 18.0 (eff 10% + degradation 10.0/MWh)"`.
3. `tempo/optimise/greedy.py::GreedyOptimiser.plan(quantiles, battery)`: using `p50`, pair the cheapest periods with the most expensive later periods, one full charge/discharge pair at a time, respecting SoC and power limits, applying the cost gate to each pair; stop when no pair passes. Returns one row per target period with `action`, `mw`, `expected_spread`, `reason` (hold reason filled when a pair failed the gate or the battery is at a limit).
4. `tempo/optimise/perfect.py::perfect_foresight(prices, battery)`: same as the LP but on actual prices. Phase 1 version: brute-force or LP; it only has to be correct, not fast.
5. `tempo/backtest/walkforward.py`:
   - `make_windows(start, end, train_days=28, test_days=7)` yields non-overlapping test weeks with their preceding train window.
   - `run_strategy(name, prices_hh, windows, strategy_fn) -> list[row]` where `strategy_fn(train_df, test_df) -> schedule_mw`.
   - Strategies in Phase 1: `simple_rule` (charge 01:00 to 05:00, discharge 17:00 to 19:00, every day), `persistence_greedy` (yesterday's prices as the forecast, greedy optimiser), `perfect`.
   - Writes `backtest_results` rows with `run_id`, `week_start`, `strategy`, `pnl_gbp`, `perfect_pnl_gbp`, `pct_of_perfect`, `regime` (regime is `'windy'` if the week's mean WINDFOR share is above the median, else `'calm'`).
6. `tempo/backtest/metrics.py::summary(results) -> DataFrame` with total £ and % of perfect per strategy, the table in description.md section 3, Layer 3.
7. `scripts/backtest.py`: runs on Tiger's `prices_hh` once Ayo's data exists; until then on synthetic.

### Tests

- `tests/unit/test_battery_physics.py` (hypothesis for random schedules and prices):
  - SoC always within `[0, capacity]`.
  - `|mw| <= power_mw` after clipping.
  - A full charge then full discharge at the same price yields `gross_pnl < 0` and equals `-(1 - eff) * energy * price` within rounding.
  - Zero schedule yields zero PnL and zero cycles.
  - Energy conservation: `sum(charged) * eff == sum(discharged) + (soc_end - soc_start)` within 1e-9 when nothing is clipped.
- `tests/unit/test_cost_gate.py`: flat prices → not ok; spread exactly at threshold → not ok; spread one penny above → ok; reason string contains the numbers.
- `tests/unit/test_greedy_known_answer.py`: a hand-built 48-period price vector (cheap at periods 4 to 7, expensive at 34 to 37) yields charge at 4 to 7 and discharge at 34 to 37 and a PnL you compute by hand in the test.
- `tests/unit/test_greedy_holds.py`: flat prices → every action is `hold` with a non-empty reason.
- `tests/unit/test_perfect_is_upper_bound.py` (hypothesis): for random price vectors, `perfect_foresight` PnL ≥ greedy on true prices ≥ simple rule.
- `tests/unit/test_walkforward_windows.py`: windows never overlap, test weeks tile the range, train window ends before test window starts.
- `tests/unit/test_backtest_synthetic.py`: on 60 synthetic days, `perfect` gets 100% every week, every other strategy ≤ 100%, `simple_rule` is positive on calm weeks, and the known-answer totals from the fixture docstring hold.
- `tests/contracts/test_backtest_contract.py` (shared, you write it): `backtest_results` schema and the ≤ 100% rule.

### Exit (Gate 2)

Backtest table on real Tiger data for simple rule, persistence + greedy, perfect. Pass the results table to Girik. **Lookahead sanity:** no strategy exceeds perfect on any week on real data. If one does, stop and find the leak with Ayo.

---

## Phase 2: Forecasters, LP, the decision engine (Gate 3, ~5 h)

### Tasks

1. `tempo/forecast/persistence.py::PersistenceForecaster`: `p50 = price_lag_1d`, `p10/p90 = p50 ± k * rolling_std` with `k` fitted on train so the band covers 80%.
2. `tempo/forecast/lgbm.py::LightGBMQuantileForecaster`: three `LGBMRegressor(objective='quantile', alpha=a)` for a in (0.1, 0.5, 0.9), small trees (`n_estimators=300, num_leaves=15, learning_rate=0.05`), features = Ayo's `build_features` columns plus `horizon_k`. Predict, then sort the three outputs per row so `p10 <= p50 <= p90`. `save/load` with joblib.
3. Training data builder `tempo/forecast/dataset.py::make_training_set(conn_or_df, decision_times) -> (X, y)`: for each historical decision time (every 6 hours over the train window), call `build_features` and join the realised price per target. Honour point-in-time by construction: features come from `build_features(decision_time)`.
4. `tempo/optimise/lp.py::LPOptimiser`: cvxpy with variables `charge[k], discharge[k] >= 0`, `soc[k]`; constraints power, capacity, SoC dynamics with efficiency; objective maximise `sum(p50 * (discharge - charge) * 0.5) - cycle_cost * sum(discharge) * 0.5 / capacity`. Optionally use `p10` for sells and `p90` for buys as a conservative variant behind a flag. Apply the cost gate post hoc per cycle to generate `reason` strings and set tiny flows to hold.
5. `tempo/decide/engine.py::run_decision(conn, now, forecaster, optimiser, run_id='live')`: `build_features` → `predict` → `plan` → write 48 `forecasts` rows and 48 `decisions` rows (one per target period) → return the `decision_id` of the first period. The schedule for the next period is what Girik's live view shows.
6. Add `tempo` (LightGBM + greedy) and `tempo_lp` strategies to the walk-forward backtest. Retrain per window on the train days only.
7. `tempo/backtest/metrics.py`: `calibration(forecasts, actuals) -> dict` with the fraction of actuals inside the p10–p90 band and a 10-bin reliability table; `by_regime(results)`.
8. `scripts/train.py`: trains on the last 90 days of Tiger data, saves `models/lgbm_{p10,p50,p90}.joblib`.

### Tests

- `tests/unit/test_persistence.py`: on synthetic, `p50` at target `t` equals the price at `t - 1 day` exactly.
- `tests/unit/test_quantile_order.py`: after `predict`, `p10 <= p50 <= p90` on every row for random inputs.
- `tests/unit/test_lgbm_beats_persistence.py`: train on 40 synthetic days, test on 14; LightGBM `p50` MAE is lower than persistence MAE (the fixture's wind signal makes this learnable). Deterministic settings: `seed=0, deterministic=True, num_threads=1`.
- `tests/unit/test_calibration_synthetic.py`: on synthetic test weeks, band coverage is between 0.80 and 0.98; the reliability table is monotone.
- `tests/unit/test_lp_vs_greedy.py` (hypothesis): LP PnL on `p50` ≥ greedy PnL on `p50` for random quantile frames; LP respects all constraints (re-simulate the LP schedule with `simulate` and assert `clipped_mwh == 0`).
- `tests/unit/test_lp_holds_on_flat.py`: flat `p50` → all hold.
- `tests/db/test_run_decision.py`: on Docker with 30 synthetic days, `run_decision(T)` writes 48 decisions and 48 forecasts with `decided_at == T`, actions in the allowed set, hold rows have a reason, and `run_id` is set.
- `tests/db/test_no_lookahead_training.py`: build the training set, then for every `(decision_time, target_time)` row assert that every feature value equals the value `build_features(decision_time)` returns (this re-derives the point-in-time guarantee at the model boundary).
- `tests/contracts/test_decisions_contract.py` (shared, you write it).

### Exit (Gate 3)

Tempo row in the backtest table on real unseen weeks. A live `run_decision` has executed on the backend at least once with a `hold` and a readable reason. Calibration number computed. Tell Girik the `decision_id` of a good decision to click.

---

## Phase 3: Self-grade and honesty metrics (Gate 4 contribution, ~3 h)

### Tasks

1. `tempo/audit/selfgrade.py` (you write the maths, Girik calls it): for each completed cycle in `decisions`, use Girik's `replay_shift` in-process for shifts −2..2 and record which shift had the best PnL. `self_grade(conn, since) -> dict` with `pct_within_one_period`, `n_cycles`, `mean_cost_of_mistiming_gbp`.
2. Regime breakdown table and calibration chart data as plain DataFrames for the dashboard.
3. "Where it's weak" generator: a function that returns plain-English lines such as "Simple rule reaches 71% of Tempo's profit on calm weeks" from `backtest_results`.

### Tests

- `tests/unit/test_selfgrade_known.py`: synthetic decisions where you deliberately shift the optimal action by +1 period on half the cycles; `pct_within_one_period == 1.0` and `mean_cost_of_mistiming_gbp > 0`. Then shift by +2 on all cycles; `pct_within_one_period == 0.0`.
- `tests/unit/test_weak_statements.py`: given a results frame with known ratios, the generated sentences contain the right percentages.

### Exit

Self-grade number on the dashboard. Honesty panel populated from real backtest output.

---

## Phase 4: Stretch (only if everything above is green)

- `tempo/forecast/nn.py`: small MLP in torch on the same features; keep only if its walk-forward % of perfect beats LightGBM on real weeks. Test: trains to lower loss than a constant on synthetic in under 30 s on CPU. Record CPU vs GPU training time if Girik's Vultr GPU exists.
- Battery-size sweep: run the backtest for capacity in {1, 2, 4, 8} MWh at 1 MW; emits a table. Test: perfect PnL is non-decreasing in capacity.
- Conservative LP variant (`p10` sells, `p90` buys) as an extra row.
