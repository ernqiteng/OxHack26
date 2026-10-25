# Tempo

A battery trading system for the GB electricity market that decides when to charge, when to sell and when to hold, then proves, half-hour by half-hour, whether it picked the right moment.

OxHack 2026. Theme: TIME. Track: HRT, Best Use of Data for Predictions and Decision Making.

## Docs

| File | What it is |
|---|---|
| [docs/description.md](docs/description.md) | What Tempo is, the three layers, the demo script, why it wins |
| [docs/needs.md](docs/needs.md) | Feasibility findings, every API, key, endpoint and env var |
| [docs/plan.md](docs/plan.md) | Implementation plan, phases, tests, frozen contracts |
| [docs/girik.md](docs/girik.md) | Part A: Data (Elexon → Tiger Data → features) |
| [docs/ernqi.md](docs/ernqi.md) | Part B: Brain (battery, optimiser, forecaster, backtest) |
| [docs/ayo.md](docs/ayo.md) | Part C: Stage (forks, workers, timing audit, dashboard, demo) |
| [docs/todo_ayo.md](docs/todo_ayo.md), [todo_girik.md](docs/todo_girik.md), [todo_ernqi.md](docs/todo_ernqi.md) | What each of us has left, checked against main and Tiger on 24 Oct evening (status re-checked 25 Oct 00:30 BST) |
| [docs/a.md](docs/a.md), [docs/b.md](docs/b.md) | Ernqi's remaining work split in two: live decisions (Part A) and backtest, replay and clean-up (Part B). Both done |
| [docs/time.md](docs/time.md) | Planned but not built: parallel backtest on the Vultr workers, battery-size sweep |
| [info.md](info.md) | Pre-hackathon idea and research. Superseded: don't quote it in the pitch |
| [docs/ui-plan.md](docs/ui-plan.md) | Two-page UI plan: Toven-style pitch page and dashboard, extracted tokens, motion spec, build order |
| [docs/ui.md](docs/ui.md) | Dashboard screen content, chart grammar and audit choreography (theme superseded by ui-plan.md) |

## Quick start

```bash
make setup            # venv, deps, .env from template
# edit .env
make db               # local TimescaleDB in Docker + schema
make test             # unit + contract tests
make test-db          # tests that need the local DB
make dashboard
```

## Pitch website

A static Next.js 15 site in `pitch/`: home (about + how it works), Tiger Data and Vultr pages. Needs Node 20+.

```bash
cd pitch
npm install
npm run dev           # http://localhost:3000, hot reload
npm run build         # static export to pitch/out/
npm start             # serve pitch/out/ locally
```

"Open the app" links to the live dashboard on the `tempo-backend` Vultr box (`http://136.244.77.120:8501`). To point it elsewhere, set `NEXT_PUBLIC_APP_URL` in `pitch/.env.local` before building.

## Before every rehearsal and before going on stage

Run the go/no-go check. It prints one line per check, then `GO` (exit code 0) or `NO-GO` (exit code 1). On Windows, use `.venv/Scripts/python` in place of `.venv/bin/python`.

```bash
.venv/bin/python scripts/demo_reset.py              # check, delete stale audit forks, pick a decision to click
.venv/bin/python scripts/demo_reset.py --dry-run    # check only, delete nothing
.venv/bin/python scripts/demo_reset.py --decision N # confirm a specific decision is replayable
.venv/bin/python scripts/demo_reset.py --fork-test  # also take and delete one real Tiger fork and time it (~30-40 s)
.venv/bin/python scripts/demo_reset.py --no-score   # skip the in-process replays used to rank decisions
```

What it checks:

| Check | Fails (NO-GO) when | Warns when |
|---|---|---|
| Tiger | the primary service is missing or not `READY` | the primary is `PAUSED` |
| Stale forks | an `audit-*` fork is left over and can't be deleted (or `--dry-run`) | |
| Service slots | no free slot for the audit's fork (the free tier holds 2 services: the primary plus one fork) | |
| Database | `TEMPO_DATABASE_URL` is unreachable | |
| Prices | `prices_hh` is empty | the newest price is over 3 hours old (poller down?) |
| Decision | no live decision has all 48 periods priced | a shifted timeline beats "as decided" (say so on stage) |
| Workers | any worker fails `/health`, or there is no pool | only local workers (Vultr not configured: don't say "Vultr"), or fewer than 5 |
| Simulator | | workers run a different simulator from this machine (rebuild the worker image) |

It picks the decision to click by replaying recent live decisions in-process. It prefers one where "as decided" beats every shift and a hold sits nearby, and prints the line to say, for example "Charging one period later would have cost £14.30". Those replays write `battery_state` rows under `audit-*` run ids, never under `live`.

Demo-day rules that follow from the Tiger free tier's two-service limit (see [docs/description.md](docs/description.md) section 11):

- Nobody creates Tiger forks or services on demo day. Any extra service takes the audit's slot.
- Click the timing audit once and wait for it to finish. A second click while the fork exists fails.
- If the fork audit fails on stage, switch the toggle to in-process and say "same replay, run locally".

The audit's fork layout is set in `.env`: `TEMPO_AUDIT_FORKS=shared` (one fork per click, the default) or `per_shift` (five forks, only with a raised service limit).

## Layout

```
tempo/        the package (see docs/plan.md section 1 for who owns what)
tests/        unit/  contracts/  db/  live/  fixtures/
scripts/      dev_db.sh  backfill.py  poll.py  train.py  backtest.py  demo_reset.py
docs/         all project documents
pitch/        the pitch website (Next.js, static export)
models/       trained model files (gitignored)
```
