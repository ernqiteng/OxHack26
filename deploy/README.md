# Deploy notes (Ayo)

| Box | Region | Plan | Units |
|---|---|---|---|
| backend | `lhr` | `vc2-1c-2gb` or bigger | `tempo-dashboard`, `tempo-poller` (Girik's) |
| worker-1..5 | `ewr` (next to the Tiger free service in us-east-1) | `vc2-1c-1gb` | `tempo-worker` |

1. Create the instance (Ubuntu 24.04, your SSH key). For the backend use the portal or `scripts/time_vultr.py --keep --label tempo-backend --region lhr`.
2. `ssh root@<ip> 'bash -s' < deploy/bootstrap.sh` (set `TEMPO_REPO_URL` first if the default is wrong).
3. Backend only: `scp .env root@<ip>:/opt/tempo/.env` then `ssh root@<ip> systemctl enable --now tempo-dashboard tempo-poller`.
4. Worker image (Phase 2): bootstrap one worker, `systemctl enable --now tempo-worker`, check `curl :8000/health`,
   then snapshot it with `VultrClient.create_snapshot` and put the id in `.env` as `VULTR_WORKER_SNAPSHOT_ID`.

Logs: `/var/log/tempo/*.log`. Dashboard: `http://<backend-ip>:8501`.
