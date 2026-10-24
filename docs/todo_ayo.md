# Ayo: what is left (as of Sat 24 Oct 2026, evening)

Status check against [ayo.md](ayo.md). Everything that could be built without teammates or Vultr is built; what remains is wiring real things together and the stage work.

## Done and verified

- Phase 0, 1, 2 code: Tiger and Vultr clients, replay, in-process and fork audits, worker service, worker pools, dashboard reading real tables, go/no-go script, worker image (snapshot `5294fe96…`, in `.env`). 143 tests green on main after the merge; live fork audit passed twice on Tiger.
- Story updated to one fork per click (description.md section 11 has the pitch line for the Tiger limit).

## Done Sat 24 Oct evening (items 1 to 5 of the first draft)

- Five Vultr workers `tempo-worker-1..5` in `ewr` from snapshot `21236d6e…` (Ernqi's simulator baked in),
  `scripts/create_workers.py` creates/lists/deletes the pool and writes `TEMPO_WORKER_URLS` to `.env`.
- Backend box `tempo-backend` in `lhr`, dashboard at http://136.244.77.120:8501, `scripts/create_backend.py`
  creates and redeploys it (`--deploy` after any code change). Poller unit installed, enabled once Girik's
  `scripts/poll.py` exists.
- Gate 2 screenshots in `docs/screenshots/`; live fork audit passed on the real pool from the test suite and
  from the public dashboard (36 s, fork + 5 workers, numbers equal to in-process).
- Dashboard: fork mode with background job, per-shift progress and log; paper theme, Report frame, header
  strip with status dots; hero sentence; rehearsal decision via `scripts/seed_selftest.py`.
- `demo_reset.py` says GO on everything except "decision" (needs Ernqi) and warns about the rehearsal rows.

## To do, in order

### Now (no one else needed)

1. ~~Create the five workers~~ done. **Create the five workers from the snapshot** in `ewr`, tag `tempo-worker`, labels `tempo-worker-1..5`, `VULTR_SSHKEY_ID` on each. Then `scripts/demo_reset.py` should stop warning about local workers, and `TEMPO_LIVE=1 pytest tests/live/test_full_audit.py -s` should run on the real pool. Record create-to-SSH timing in needs.md B4 (still unticked).
2. ~~Backend box~~ done. **Backend box** in `lhr` (`vc2-1c-2gb`): `deploy/bootstrap.sh` with `ROLE=backend`, copy `.env`, enable `tempo-dashboard` and (once Girik's `scripts/poll.py` exists) `tempo-poller`. The dashboard needs `TEMPO_DATABASE_URL` and the Tiger keys on the box; the box must be in Vultr's API allow-list if it ever calls Vultr.
3. ~~Gate 2 screenshot~~ done. **Gate 2 screenshot.** The dashboard against Tiger now shows real prices (two years) and Ernqi's real backtest table. Take it and put it in `docs/` or the repo wiki; ayo.md asks for it.
4. ~~Dashboard fork mode~~ done. **Dashboard fork mode** (ayo.md Phase 2 task 5, ui.md step 4 to 5): the "forks" toggle still runs in-process. Run `run_audit(mode='fork')` in a background thread, poll `AuditProgress` with a fragment, show per-shift states and the log, disable the button while running. This is the one visible gap in the live demo.
5. ~~UI build~~ done (Streamlit option A; the Next.js pitch page in ui-plan.md steps 1 to 5 is not started). **UI build** per ui.md steps 1 to 4 and 6 (header strip with status dots, Live chart with now-rule and action glyphs, five bordered audit columns with the generated sentence, Honesty ladder), with the visual theme from ui-plan.md, which supersedes ui.md section 3. ui-plan.md and the matching README and ui.md edits are still uncommitted in the working tree.

### When Girik's poller exists

6. ~~Enable `tempo-poller` on the backend box~~ done: `tempo-poller` runs on `tempo-backend` (enabled by `create_backend.py --deploy` once `scripts/poll.py` existed).

### When Ernqi has live decisions

7. ~~Run `scripts/demo_reset.py` until it says GO … **Gate 3.**~~ done: decision #441 clicked live in fork mode, 74 s, screenshots `gate3_*.png` (ayo.md header). **Replaced:** #441 was in-sample (a.md, Correction); the demo decision is now **#1353**, audited in fork mode in 32 s, as decided is best. Retake the `gate3_*.png` screenshots with #1353.
8. Self-grade line: the number exists (after the out-of-sample regeneration: 87.5% within one period over 8 cycles, £6.37 mean cost of mistiming; the in-sample figure was 100% and £0.51). Still to do: check it renders on the box.
9. Replay tab on Ernqi's stored windy week: `create_backend.py --deploy` now ships `models/replay_week.*` (it used to skip them, so the box showed the synthetic week); confirm on the box after the next deploy. Honesty calibration from real forecasts: done, with a verdict sentence (after the regeneration: 405 settled, 40% vs 80%; the in-sample figure was 77%). Forecast bands on Live from `forecasts`: not checked.

### Stage

10. Rehearse the full path twice from `demo_reset.py` to the closing line; time the fork wait and say the section 11 challenge during it.
11. Full backup recording, stored off the laptop. Print the script (description.md section 6) with the in-process fallback line.
12. Demo-day checklist in ayo.md: venue Wi-Fi and hotspot, `demo_reset.py` GO, Live tab open, backup video open, decision confirmed.
13. ~~**Gate lines:** write Gate 2 and 3 dates at the top of ayo.md.~~ done (ayo.md header).

## Watch-outs

- Only two Tiger services may exist: primary plus the audit's fork. `demo_reset.py` fails if anything else holds the slot.
- Workers on public IPs require `TEMPO_WORKER_TOKEN`; the laptop's `.env` has it, `create_backend.py --deploy` copies it to the box.
- Before the demo: `scripts/seed_selftest.py --remove`, then `scripts/demo_reset.py` must say GO. (The selftest rows were already gone from Tiger on 24 Oct evening: 0 rows.)
- To ship code changes to the workers, rebuild the image (`scripts/build_worker_image.py`) and recreate the five; the image carries a copy of the repo, not a git checkout.
- ~~`make lint` is red on main~~: clean on main since PR #16 (`ruff check .` and `ruff format --check .`).
