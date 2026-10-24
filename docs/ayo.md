# Part C: Stage (Ayo)

Gate reached: _(write date/time here as you pass each gate)_

You own everything the judges see and everything that spins up on demand: Tiger forks, Vultr workers, the timing-audit orchestration, the dashboard and the demo itself. Your part has the highest on-stage risk, so your tests focus on equivalence (the fancy path gives the same answer as the simple path) and on failure handling (one worker dying must not kill the view).

**You own:** `tempo/infra/`, `tempo/audit/` (except `selfgrade.py`, Ernqi writes the maths), `tempo/worker/`, `tempo/dashboard/`, `scripts/demo_reset.py`, the backend box, the worker pool, the backup recording.

**You depend on:** Ernqi's `Battery` and `simulate` (Phase 1) for replay; Ernqi's `decisions` rows (Phase 2) for the audit; Girik's `prices_hh` (Phase 1) and `storage_stats` (Phase 3) for the dashboard. Until they land, you work against the synthetic fixture and against `decisions` rows you insert yourself in tests.

**Others depend on you for:** `replay_shift` (Ernqi's self-grade, Phase 3), the backend box where Girik's poller runs (Phase 2), the dashboard that shows everyone's work.

Tiger and Vultr endpoints, limits and the pre-warm reasoning are in [needs.md](needs.md) sections B1, B2 and B4.

---

## Phase 0: Accounts, timings, skeleton (~90 min)

### Tasks

1. Vultr: API key, check Billing → Limits (need ≥ 6 instances), request an increase now if lower. Deploy one `vc2-1c-1gb` in `ewr` from the API and time create → `active` → SSH-able. Write the number in needs.md B4.
2. Tiger: project ID and client credentials. Fork Girik's free service once with `fork_strategy: "NOW"` via REST, poll to `READY`, time it, delete it. Write the number in needs.md B2.
3. `tempo/infra/tiger.py::TigerClient` and `tempo/infra/vultr.py::VultrClient` skeletons with the method signatures from plan.md 2.2, using `httpx`.
4. `tempo/dashboard/app.py`: Streamlit skeleton with the five tabs from the demo script (Live, Replay, Timing audit, Honesty, About), each rendering the synthetic fixture.
5. Backend box: one Vultr instance in `lhr` with Python, the repo, `.env`, and a `systemd` unit template for Girik's poller and for the Streamlit app.

### Tests

- `tests/unit/test_tiger_client.py` (respx): `fork` posts the right body and auth header; `wait_ready` polls `QUEUED → CONFIGURING → READY` and returns; `wait_ready` raises after a timeout; `delete` sends DELETE.
- `tests/unit/test_vultr_client.py` (respx): `list_workers` filters instances by tag `tempo-worker`; `pick_idle` returns one with `status == 'active'` and no current job; raises a clear error when none idle.
- `tests/live/test_tiger_fork_roundtrip.py` (`@pytest.mark.live`): real fork, wait, connect with `initial_password`, `SELECT 1`, delete in `finally`.

### Exit

Timings written down. Clients merged. Dashboard skeleton runs locally with `streamlit run`.

---

## Phase 1: Replay, dashboard on real data (Gate 2 contribution, ~4 h)

### Tasks

1. `tempo/audit/shifts.py::replay_shift(conn, decision_id, shift, run_id) -> float`:
   - Load the decision's 48-period schedule from `decisions` (all rows with the same `decided_at` and original `run_id`).
   - Shift the schedule by `shift` periods (`np.roll` with the wrapped-around periods set to hold).
   - Load actual prices for those targets from `prices_hh`.
   - Load SoC at `decided_at` from `battery_state` for the original run (or `capacity / 2` if none).
   - `simulate` (Ernqi's) and write the resulting `soc_path` and cumulative PnL into `battery_state` under the given `run_id`, then return `pnl_gbp`.
   - Pure function of the database contents: same inputs, same output, every time.
2. `tempo/audit/orchestrator.py::run_audit(conn, decision_id, mode='inprocess') -> list[AuditRow]`: for shifts −2..2, call `replay_shift` with `run_id = f'audit-{decision_id}-{shift}'`, compute `pnl_delta_gbp = pnl[shift] - pnl[0]`, write `audits` rows. Phase 1 supports only `mode='inprocess'`.
3. Dashboard:
   - **Live tab:** current settlement period (computed from UTC now), latest 24 h of `prices_hh`, today's schedule from `decisions` where `run_id='live'` (empty until Phase 2), most recent hold with reason.
   - **Honesty tab:** `backtest_results` summary table (Ernqi's `summary`), with the four rows from description.md.
   - **Timing audit tab:** pick a decision, button runs `run_audit(mode='inprocess')`, renders five columns with PnL and delta, real decision highlighted.
   - Reads from Tiger via `TEMPO_DATABASE_URL`; cache queries for 30 s.

### Tests

- `tests/db/test_replay_shift_zero.py`: insert 48 synthetic decisions and prices on Docker; `replay_shift(id, 0, 'test')` equals `simulate` called directly on the same schedule and prices, to the penny.
- `tests/db/test_replay_shift_moves.py`: a schedule that charges at periods 4 to 7 shifted by +1 charges at 5 to 8 in the written `battery_state` SoC path; shifting by −2 on a schedule that charges at period 1 drops the wrapped rows (hold) and the PnL reflects it.
- `tests/db/test_replay_isolated.py`: running `replay_shift` under `run_id='x'` writes no rows with `run_id='live'`.
- `tests/db/test_run_audit_inprocess.py`: five `audits` rows, `shift 0` has `pnl_delta_gbp == 0`, `mode == 'inprocess'`, `finished_at >= started_at`.
- `tests/unit/test_dashboard_smoke.py` (`streamlit.testing.v1.AppTest`): the app runs without exceptions against a stub connection returning the synthetic fixture; each tab renders at least one chart or table.
- `tests/contracts/test_audits_contract.py` (shared, you write it).

### Exit (Gate 2, with Girik and Ernqi)

Dashboard on the backend box shows Girik's real live period and Ernqi's real backtest table. In-process audit works on a synthetic decision. This is the first real demo; screenshot it.

---

## Phase 2: Forks and workers (Gate 3 contribution, ~5 h)

### Tasks

1. `tempo/worker/main.py`: FastAPI service on each worker, `POST /replay {database_url, decision_id, shift, run_id}` → runs `replay_shift` against the given fork URL and returns `{pnl_gbp, started_at, finished_at, worker_id}`. `GET /health`. Reads nothing from env except its own id. Runs under `systemd`, starts on boot.
2. Worker image: build one instance, install the repo and service, snapshot it. Create 5 workers from the snapshot with tag `tempo-worker` and labels `tempo-worker-1..5`. Write the snapshot id and plan to `.env`.
3. `TigerClient` completion: `fork` returns `Service` with `endpoint.host/port` and `initial_password`; `connection_url(service)` builds the DSN; `delete_all_forks(prefix='audit-')` for cleanup.
4. `run_audit(mode='fork')`:
   - Fork the primary service five times concurrently (`asyncio` + `httpx.AsyncClient`), names `audit-{decision_id}-{shift}`.
   - `wait_ready` each; as each becomes ready, `pick_idle` a worker and `POST /replay` with that fork's DSN.
   - Collect results; write `audits` rows with `mode='fork'`, `fork_service_id`, `worker_id`, timings.
   - Delete the forks in `finally`, even on failure.
   - Per-shift timeout (default 180 s). A failed shift writes an `audits` row with `pnl_gbp = NULL` and the view shows "failed" for that column; the other four still render.
5. Dashboard Timing audit tab: mode toggle (in-process / forks), live progress per shift ("forking… ready… replaying on tempo-worker-3… £-14.20"), total elapsed time, and the sentence "charging one period later would have cost £X".

### Tests

- `tests/db/test_fork_equals_inprocess.py` (the key test; Docker only, no cloud): simulate a "fork" by `pg_dump`/restore or by `CREATE DATABASE fork TEMPLATE tempo` on the local Docker, call the worker's `replay_shift` code path against the copy via the FastAPI `TestClient`, assert the PnL equals `run_audit(mode='inprocess')` to the penny for all five shifts.
- `tests/unit/test_orchestrator_fake_clients.py`: fake `TigerClient` and fake workers; five forks created with the right names, each deleted at the end, including when one worker raises; the failed shift row has `pnl_gbp IS NULL`; the elapsed time per shift is recorded.
- `tests/unit/test_worker_api.py` (`TestClient`): `/health` 200; `/replay` with a bad DSN returns 500 with a message, not a hang (timeout 10 s).
- `tests/live/test_full_audit.py` (`@pytest.mark.live`): one real `run_audit(mode='fork')` on Tiger with the real pool; asserts five rows, no forks left behind, total time under 180 s. Run it once at Phase 2 exit and once at Gate 5.

### Exit (Gate 3, with Ernqi)

Click a real decision, five forks, five workers, five numbers, under two minutes, forks cleaned up. Record a screen capture now as the first backup.

---

## Phase 3: Stage polish (Gate 4, ~4 h)

### Tasks

1. **Pre-warm and resilience:** `scripts/demo_reset.py` checks the five workers' `/health`, deletes stale `audit-*` forks, verifies the primary service is `READY`, picks a good `decision_id` (Ernqi gives you one), and prints a go/no-go line. Run it before every rehearsal.
2. **Replay tab:** choose a historical windy week, animate forward period by period: forecast band vs actual, battery SoC, cumulative £. Use `backtest_results` and a stored schedule for that week from Ernqi.
3. **Honesty tab:** calibration chart (Ernqi's reliability table), regime breakdown, "where it's weak" sentences, Girik's `storage_stats` line ("X rows, compressed Y%").
4. **Live tab:** uncertainty bands on the next 24 h from `forecasts`, today's schedule, hold reasons.
5. Self-grade line from Ernqi's `self_grade` on the Timing audit tab.
6. Backup: full recorded run of the demo path. Store it off the laptop too.

### Tests

- `tests/unit/test_demo_reset.py`: with fake clients, reports no-go when a worker is unhealthy or a stale fork exists; go when clean.
- `tests/unit/test_dashboard_smoke.py` extended: every tab renders with a full synthetic dataset, including an `audits` set with one failed shift.
- `tests/live/test_full_audit.py` again at Gate 5.

### Exit (Gate 4 then 5)

Full demo path rehearsed twice from `demo_reset.py` to the closing line. Backup recorded. Script printed.

---

## Phase 4: Stretch (only if everything above is green)

- Vultr GPU instance for Ernqi's NN training if the plan is available; record CPU vs GPU times for the honesty panel.
- Parallel walk-forward backtest on the worker pool (`POST /backtest_window`) with a reported speed-up versus serial; test: results identical to the serial run.
- Battery-size sweep dispatched to the pool, same equivalence test.

---

## Demo day checklist

1. Laptop on venue Wi-Fi and phone hotspot tested as fallback.
2. `python scripts/demo_reset.py` says go.
3. Dashboard open on the Live tab, backup video open in another window.
4. Decision to click confirmed with Ernqi.
5. Script from description.md section 6 printed, with the fallback timings if the fork audit fails (switch to in-process mode on the toggle and say "same replay, run locally").
