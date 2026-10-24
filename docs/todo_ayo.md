# Ayo: what is left (as of Sat 24 Oct 2026, evening)

Status check against [ayo.md](ayo.md). Everything that could be built without teammates or Vultr is built; what remains is wiring real things together and the stage work.

## Done and verified

- Phase 0, 1, 2 code: Tiger and Vultr clients, replay, in-process and fork audits, worker service, worker pools, dashboard reading real tables, go/no-go script, worker image (snapshot `5294fe96…`, in `.env`). 143 tests green on main after the merge; live fork audit passed twice on Tiger.
- Story updated to one fork per click (description.md section 11 has the pitch line for the Tiger limit).

## To do, in order

### Now (no one else needed)

1. **Create the five workers from the snapshot** in `ewr`, tag `tempo-worker`, labels `tempo-worker-1..5`, `VULTR_SSHKEY_ID` on each. Then `scripts/demo_reset.py` should stop warning about local workers, and `TEMPO_LIVE=1 pytest tests/live/test_full_audit.py -s` should run on the real pool. Record create-to-SSH timing in needs.md B4 (still unticked).
2. **Backend box** in `lhr` (`vc2-1c-2gb`): `deploy/bootstrap.sh` with `ROLE=backend`, copy `.env`, enable `tempo-dashboard` and (once Girik's `scripts/poll.py` exists) `tempo-poller`. The dashboard needs `TEMPO_DATABASE_URL` and the Tiger keys on the box; the box must be in Vultr's API allow-list if it ever calls Vultr.
3. **Gate 2 screenshot.** The dashboard against Tiger now shows real prices (two years) and Ernqi's real backtest table. Take it and put it in `docs/` or the repo wiki; ayo.md asks for it.
4. **Dashboard fork mode** (ayo.md Phase 2 task 5, ui.md step 4 to 5): the "forks" toggle still runs in-process. Run `run_audit(mode='fork')` in a background thread, poll `AuditProgress` with a fragment, show per-shift states and the log, disable the button while running. This is the one visible gap in the live demo.
5. **UI build** per ui.md steps 1 to 4 and 6 (header strip with status dots, Live chart with now-rule and action glyphs, five bordered audit columns with the generated sentence, Honesty ladder), with the visual theme from ui-plan.md, which supersedes ui.md section 3. ui-plan.md and the matching README and ui.md edits are still uncommitted in the working tree.

### When Girik's poller exists

6. Enable `tempo-poller` on the backend box. Until then the Live tab's prices are a day stale (newest 24 Oct 00:00 UTC).

### When Ernqi has live decisions

7. Run `scripts/demo_reset.py` until it says GO; confirm the decision with Ernqi. Click it in fork mode on stage hardware. **Gate 3.** Record the first screen capture as backup.
8. Self-grade line: `DbSource.self_grade()` already calls Ernqi's `self_grade`; check the number renders once cycles exist.
9. Replay tab on Ernqi's stored windy week; Honesty calibration from real forecasts; forecast bands on Live from `forecasts`.

### Stage

10. Rehearse the full path twice from `demo_reset.py` to the closing line; time the fork wait and say the section 11 challenge during it.
11. Full backup recording, stored off the laptop. Print the script (description.md section 6) with the in-process fallback line.
12. Demo-day checklist in ayo.md: venue Wi-Fi and hotspot, `demo_reset.py` GO, Live tab open, backup video open, decision confirmed.
13. **Gate lines:** write Gate 2 and 3 dates at the top of ayo.md.

## Watch-outs

- Only two Tiger services may exist: primary plus the audit's fork. `demo_reset.py` fails if anything else holds the slot.
- Workers on public IPs require `TEMPO_WORKER_TOKEN`; the laptop's `.env` has it, the backend box's `.env` must too.
- To ship code changes to the workers, rebuild the image (`scripts/build_worker_image.py`) and recreate the five; the image carries a copy of the repo, not a git checkout.
- `make lint` is red on main because of teammates' files, not yours; the pre-push hook will complain until Ernqi fixes item 10 in their list.
