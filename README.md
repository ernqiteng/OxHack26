# Tempo

A battery trading system for the GB electricity market that decides when to charge, when to sell and when to hold, then proves, half-hour by half-hour, whether it picked the right moment.

OxHack 2026. Theme: TIME. Track: HRT, Best Use of Data for Predictions and Decision Making.

## Docs

| File | What it is |
|---|---|
| [docs/description.md](docs/description.md) | What Tempo is, the four layers, the demo script, why it wins |
| [docs/needs.md](docs/needs.md) | Feasibility findings, every API, key, endpoint and env var |
| [docs/plan.md](docs/plan.md) | Implementation plan, phases, tests, frozen contracts |
| [docs/girik.md](docs/girik.md) | Part A: Data (Elexon → Tiger Data → features) |
| [docs/ernqi.md](docs/ernqi.md) | Part B: Brain (battery, optimiser, forecaster, backtest) |
| [docs/ayo.md](docs/ayo.md) | Part C: Stage (forks, workers, timing audit, dashboard, demo) |

## Quick start

```bash
make setup            # venv, deps, .env from template
# edit .env
make db               # local TimescaleDB in Docker + schema
make test             # unit + contract tests
make test-db          # tests that need the local DB
make dashboard
```

## Layout

```
tempo/        the package (see docs/plan.md section 1 for who owns what)
tests/        unit/  contracts/  db/  live/  fixtures/
scripts/      dev_db.sh  backfill.py  poll.py  train.py  backtest.py  demo_reset.py
docs/         all project documents
models/       trained model files (gitignored)
```
