# Tempo: implementation plan

Companion to [description.md](description.md) (what we are building) and [needs.md](needs.md) (accounts, keys, endpoints). This file is how we build it, in what order, and how we prove each phase works before moving on.

Three developers, three independent parts:

| Part | Owner | File | One line |
|---|---|---|---|
| A: Data | Girik | [girik.md](girik.md) | Elexon → Tiger Data hypertables → aggregates → point-in-time features |
| B: Brain | Ernqi | [ernqi.md](ernqi.md) | Battery sim → optimiser → forecaster → walk-forward backtest → honesty metrics |
| C: Stage | Ayo | [ayo.md](ayo.md) | Tiger forks + Vultr workers → timing audit → dashboard → demo |

The parts are independent because of three things agreed in Phase 0 and never changed afterwards: the **database schema**, the **Python interfaces** between modules, and a **synthetic fixture dataset** that B and C build against before A's real data lands.

---

## 1. Repo layout

```
tempo/
  __init__.py
  config.py            settings from env (.env), battery params, paths      (shared, Phase 0)
  db/
    schema.sql         hypertables, aggregates, policies                    (A)
    conn.py            get_conn(), run_sql(), copy_rows()                   (A)
  ingest/
    elexon.py          HTTP client, chunking, stream endpoints              (A)
    backfill.py        two-year bulk load                                   (A)
    poll.py            live poller                                          (A)
  features/
    build.py           build_features(conn, decision_time) -> DataFrame     (A)
  sim/
    battery.py         Battery dataclass, step(), simulate(schedule, prices) (B)
  forecast/
    persistence.py     PersistenceForecaster                                (B)
    lgbm.py            LightGBMQuantileForecaster                           (B)
    nn.py              stretch                                              (B)
  optimise/
    greedy.py          GreedyOptimiser                                      (B)
    lp.py              LPOptimiser (cvxpy)                                  (B)
    gate.py            cost gate                                            (B)
  backtest/
    walkforward.py     windows, strategies, results table                   (B)
    metrics.py         pct_of_perfect, calibration, regime split            (B)
  decide/
    engine.py          run_decision(conn, now) -> writes decisions           (B, uses A + B)
  audit/
    shifts.py          in-process shift replay                              (C, uses B.sim)
    orchestrator.py    fork → dispatch → collect                            (C)
  infra/
    tiger.py           TigerClient: fork, status, delete                    (C)
    vultr.py           VultrClient: list, create, pool                      (C)
  worker/
    main.py            HTTP service on each Vultr worker: /replay           (C)
  dashboard/
    app.py             Streamlit app                                        (C)
tests/
  fixtures/
    synthetic.py       make_synthetic_market(days=...) deterministic        (shared, Phase 0)
    elexon_samples/    one real JSON response per dataset                   (A)
  unit/                fast, no network, no DB
  db/                  needs local TimescaleDB (docker)                     
  live/                needs real Tiger/Vultr/Elexon, skipped by default
  contracts/           interface tests all three devs must keep green
scripts/
  dev_db.sh            docker run timescale/timescaledb-ha, apply schema
  backfill.py, poll.py, train.py, backtest.py, demo_reset.py
docs/                  description.md, needs.md, plan.md, girik.md, ernqi.md, ayo.md
models/                trained models (gitignored)
.env.example
pyproject.toml         deps, pytest markers, ruff
Makefile               make setup / test / test-db / test-live / lint / db / dashboard
```

---

## 2. Shared contracts (frozen at end of Phase 0)

### 2.1 Database schema (A owns the SQL, everyone depends on it)

All timestamps `timestamptz` in UTC. All hypertables partitioned on the first column.

```sql
-- raw market data, one table, long format
grid_raw(
  start_time        timestamptz NOT NULL,   -- period/hour start
  available_at      timestamptz NOT NULL,   -- Elexon publishTime, or derived for MID
  dataset           text NOT NULL,          -- 'MID','WINDFOR','NDF','INDO','FUELHH','DISEBSP'
  series            text NOT NULL,          -- provider / fuelType / boundary / ''
  value             double precision NOT NULL,
  settlement_date   date,
  settlement_period smallint,
  PRIMARY KEY (start_time, available_at, dataset, series)
);

-- half-hourly APX price, the one series everything trades on
prices_hh      (bucket timestamptz, price double precision, volume double precision)  -- continuous aggregate
prices_daily   (bucket timestamptz, mean, min, max, spread)                             -- on prices_hh
prices_weekly  (bucket timestamptz, mean, stddev, spread_mean)                          -- on prices_daily

forecasts(
  forecast_id   bigserial, decided_at timestamptz NOT NULL, target_time timestamptz NOT NULL,
  p10 double precision, p50 double precision, p90 double precision, model text
);

decisions(
  decision_id    bigserial, decided_at timestamptz NOT NULL, target_time timestamptz NOT NULL,
  action         text CHECK (action IN ('charge','discharge','hold')),
  mw             double precision,       -- signed power for the period, 0 for hold
  reason         text,                   -- e.g. 'spread 12.3 < cost 18.0'
  expected_spread double precision, forecast_id bigint, run_id text
);

battery_state(
  ts timestamptz NOT NULL, soc_mwh double precision, cum_pnl_gbp double precision, run_id text
);

audits(
  audit_id bigserial, decision_id bigint, shift smallint,   -- -2..2
  pnl_gbp double precision, pnl_delta_gbp double precision,
  mode text CHECK (mode IN ('inprocess','fork')),
  fork_service_id text, worker_id text,
  started_at timestamptz, finished_at timestamptz
);

backtest_results(
  run_id text, week_start date, strategy text, pnl_gbp double precision,
  perfect_pnl_gbp double precision, pct_of_perfect double precision, regime text
);
```

`run_id` is `'live'` for the real system; forks and backtests write their own ids, so replays never collide with live rows.

### 2.2 Python interfaces

```python
# tempo/features/build.py                                   (A)
def build_features(conn, decision_time: datetime, horizon: int = 48) -> pd.DataFrame
    # one row per target period (decision_time + 30min*k, k=1..48)
    # columns: target_time, plus feature columns; uses ONLY rows with available_at <= decision_time
    # index: target_time

# tempo/sim/battery.py                                      (B)
@dataclass
class Battery:  capacity_mwh=2.0; power_mw=1.0; rt_efficiency=0.90; cycle_cost_gbp=20.0; soc_mwh=1.0
def simulate(battery, schedule_mw: np.ndarray, prices: np.ndarray) -> SimResult  # .pnl_gbp, .soc_path, .cycles

# tempo/forecast/*.py                                       (B)
class Forecaster(Protocol):
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None
    def predict(self, X: pd.DataFrame) -> pd.DataFrame     # columns p10, p50, p90, index = target_time

# tempo/optimise/*.py                                       (B)
class Optimiser(Protocol):
    def plan(self, quantiles: pd.DataFrame, battery: Battery) -> pd.DataFrame
    # returns one row per target_time: action, mw, expected_spread, reason

# tempo/decide/engine.py                                    (B)
def run_decision(conn, now: datetime, forecaster, optimiser, run_id='live') -> int   # returns decision_id

# tempo/audit/shifts.py                                     (C)
def replay_shift(conn, decision_id: int, shift: int, run_id: str) -> float  # pnl_gbp, writes battery_state under run_id

# tempo/infra/tiger.py                                      (C)
class TigerClient:  fork(service_id, name) -> Service;  wait_ready(service_id) -> Service;  delete(service_id)
# tempo/infra/vultr.py                                      (C)
class VultrClient:  list_workers() -> list[Worker];  pick_idle() -> Worker
```

### 2.3 Synthetic fixture (shared, written in Phase 0 by B, used by all)

`tests/fixtures/synthetic.py::make_synthetic_market(days=60, seed=0)` returns a DataFrame in the `grid_raw` long format with:

- an APX price with a deterministic daily shape (cheap 01:00 to 05:00, expensive 17:00 to 19:00), weekly effect, a "windy" regime on even weeks that depresses night prices, and Gaussian noise;
- a WINDFOR series that is correlated with the price dip (so a model can learn something);
- NDF demand correlated with the evening peak;
- `available_at` set realistically (WINDFOR published 30 min before start, MID at `start + 30min + 10min`).

Known-answer values are documented in the docstring (for example "perfect-foresight profit over 7 days with the default battery is 1 234.5 ± 0.1"), so tests can assert against them.

---

## 3. Phases, tests and exit criteria

Phases map to the gates in description.md. **No one moves to the next phase until that phase's tests are green and the exit criteria are checked off in the repo.** Each dev has their own column; "Integration" is what has to be true across parts.

### Phase 0: Setup and contracts (Gate 0, first ~90 minutes, everyone together)

| Who | Tasks |
|---|---|
| All | Clone repo, `make setup` (venv, deps), copy `.env.example`, run `make test` on the empty skeleton |
| A | Create Tiger free service, client credentials, write `schema.sql` draft, `scripts/dev_db.sh` for local TimescaleDB in Docker |
| B | Write `tests/fixtures/synthetic.py` with known answers; write `tempo/sim/battery.py` stub with the dataclass |
| C | Create Vultr API key, check account limits, create Tiger REST credentials, time one real fork, deploy one tiny Vultr instance and time it |
| All | Review and freeze section 2 of this file. Record Gate 0 decisions in needs.md B8 |

**Tests at exit:** `tests/contracts/test_schema.py` applies `schema.sql` to the local Docker TimescaleDB and asserts every table and aggregate exists. `tests/unit/test_synthetic.py` asserts the fixture is deterministic and matches its known answers.

**Exit criteria:** schema applied on local Docker and on the Tiger free service. One fork timed (number written down). One Vultr instance timed. `make test` green. Three devs can now work without talking to each other for several hours.

### Phase 1: Foundations (Gate 1 for A; Gate 2 groundwork for B; infra clients for C)

| Who | Deliverable | Tests |
|---|---|---|
| A | Elexon client, backfill of 2 years into local DB then Tiger, aggregates building | Unit: parsing every dataset from saved samples, 7-day chunking, availability_at rules, clock-change day. DB: idempotent re-run, aggregates match pandas |
| B | Battery sim, greedy optimiser, cost gate, perfect foresight, walk-forward harness, simple-rule baseline | Unit: physics invariants, known answers on synthetic, perfect ≥ everything |
| C | TigerClient, VultrClient, in-process shift replay, dashboard skeleton reading synthetic data | Unit: mocked HTTP for both clients. Live (opt-in): real fork create/ready/delete |

**Integration at exit:** B's backtest runs on A's real `prices_hh` from Tiger. C's dashboard shows A's live settlement period and B's backtest table. This is **Gate 2: the baseline demo**.

### Phase 2: Tempo decides (Gate 3)

| Who | Deliverable | Tests |
|---|---|---|
| A | Live poller running on the backend, `build_features` on real data, point-in-time guarantee | DB: leak test (future row inserted, not used), feature lags correct, poller only fetches when metadata changes |
| B | Persistence and LightGBM quantile forecasters, `run_decision`, LP optimiser | Unit: quantile ordering, calibration on synthetic, LightGBM beats persistence on synthetic, LP ≥ greedy. DB: `run_decision` writes decisions + forecasts |
| C | Fork orchestrator, worker service, equivalence of fork replay and in-process replay | Unit: orchestrator with fake clients. DB: fork replay == in-process replay to the penny. Live: one real 5-fork audit |

**Integration at exit:** Tempo row appears in the backtest table on real unseen weeks. A real decision in `decisions` with a hold and a reason. Clicking it runs the in-process audit. **Gate 3.**

### Phase 3: Timing audit on stage (Gate 4)

| Who | Deliverable | Tests |
|---|---|---|
| A | Compression policy, "X rows compressed Y%" query, performance check of the 2-year query | DB: compression stats query returns, two-year query under 1 s |
| B | Running self-grade (in-process shifts on every completed cycle), calibration chart data, regime breakdown | Unit: self-grade % computed correctly on synthetic with known timing errors |
| C | Live fork + Vultr audit from the dashboard, pre-warmed pool, side-by-side view | Live: click to results under 2 minutes, forks deleted afterwards, failure of one worker does not break the view |

**Integration at exit:** full demo path runs end to end on real data. **Gate 4.**

### Phase 4: Polish and freeze (Gates 5 and 6)

- Stretch items only if their tests are green: LP as default, NN vs LightGBM, battery-size sweep, pgvector similar days.
- Record a backup run of the full demo.
- Rehearse the 3-minute script twice. Freeze. Nothing new after that.

---

## 4. Test strategy

### 4.1 Tiers

| Tier | Command | Needs | Runtime target | When |
|---|---|---|---|---|
| Unit | `make test` | nothing | < 30 s | every commit, pre-push hook |
| DB | `make test-db` | Docker TimescaleDB on localhost:5433 | < 3 min | before each phase exit and before merging to main |
| Contracts | part of `make test` | nothing | < 10 s | every commit; a red contract test blocks everyone, fix first |
| Live | `make test-live` | `.env` with real Tiger, Vultr | minutes, costs money | once per phase exit, by the owning dev |

Live tests are marked `@pytest.mark.live` and skipped unless `TEMPO_LIVE=1`. They clean up what they create (forks, instances) in `finally` blocks.

### 4.2 Rules

1. **Known answers, not "it ran."** Every numeric test asserts a value computed by hand or by an independent method (pandas versus SQL, brute force versus LP).
2. **Point-in-time is tested adversarially.** Insert a row with `available_at` in the future and assert it changes nothing. This test lives in contracts and all three parts call it.
3. **Equivalence tests between slow and fast paths.** Fork replay must equal in-process replay. LP must be at least as good as greedy. Compressed chunks must return the same rows as uncompressed.
4. **Determinism.** Seeds everywhere. Synthetic fixture is seeded. LightGBM gets `seed=0, deterministic=True, num_threads=1` in tests.
5. **No test talks to Elexon** except in the live tier. Real responses are saved once into `tests/fixtures/elexon_samples/` and replayed.
6. **Lookahead sanity check at Gate 2 and Gate 3:** on the backtest, only the perfect-foresight strategy may beat perfect foresight's own number for any week; every other strategy must be ≤ it. If Tempo ever exceeds perfect foresight on any week, there is a leak. This is a test, not a glance at a chart.

### 4.3 Tooling

- `pytest`, `pytest-cov`, `respx` (mock httpx), `freezegun` (fix `now`), `hypothesis` for battery invariants.
- `ruff` for lint and format. `make lint` runs in the pre-push hook with `make test`.
- Local DB: `docker run -d --name tempo-db -p 5433:5432 -e POSTGRES_PASSWORD=tempo timescale/timescaledb-ha:pg17`. `scripts/dev_db.sh` wraps this and applies `schema.sql`.

---

## 5. Integration points and ownership of the seams

| Seam | Producer | Consumer | Contract test |
|---|---|---|---|
| `grid_raw` + aggregates | A | B (backtest), C (dashboard) | `test_schema.py`, `test_pit_leak.py` |
| `build_features` | A | B (`run_decision`) | `test_features_contract.py`: columns, index, no NaN in required columns, no future rows |
| `simulate`, `Battery` | B | C (`replay_shift`, worker) | `test_battery_contract.py`: signature and known answer |
| `decisions`, `forecasts` rows | B | C (audit, dashboard) | `test_decisions_contract.py`: one decision per target period, action in set, reason non-empty on hold |
| `audits` rows | C | C dashboard, B self-grade | `test_audits_contract.py`: five shifts per audit, shift 0 delta is 0 |
| `backtest_results` | B | C dashboard | `test_backtest_contract.py`: perfect = 100%, others ≤ 100% |

If you need to change a contract after Phase 0, you tell the other two first, change the contract test in the same commit, and they pull before continuing.

---

## 6. Working agreements

- **Branches:** `a/<topic>`, `b/<topic>`, `c/<topic>`. Merge to `main` only with `make test` green. Rebase on `main` at least every two hours.
- **Fixtures first.** If you are blocked on another part, build against `make_synthetic_market` or the saved Elexon samples. Never wait.
- **Secrets** live in `.env` only. `.env.example` lists every key with a blank value.
- **Run IDs.** Anything that writes `battery_state` or `decisions` outside the live system uses its own `run_id`. The dashboard shows `run_id='live'` only.
- **Time.** UTC in the database and in code. Local time only in the dashboard's labels.
- **Stop line.** When a phase's exit criteria are met, write the gate date and time at the top of your own file and move on. If the clock says it is time for Gate 5 and you are not at Gate 4, cut from the bottom of your file's "stretch" section, not from tests.

---

## 7. Demo preparation (owned by C, everyone rehearses)

1. `scripts/demo_reset.py`: deletes stale forks, confirms the five workers are up, picks a decision to click (one with a hold nearby and a clear "one period later costs £X" result), and prints the demo state.
2. Backup recording of the full path, captured at Gate 5.
3. Printed one-page script from description.md section 6, with the fallback timings.
4. Hotspot tested as the network fallback for the laptop.
