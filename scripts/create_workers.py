#!/usr/bin/env python3
"""Create (or tear down) the pre-warmed worker pool from the snapshot built by build_worker_image.py.

    .venv/bin/python scripts/create_workers.py            # ensure tempo-worker-1..5 exist, boot, pass /health
    .venv/bin/python scripts/create_workers.py --count 3  # a smaller pool (the audit queues timelines)
    .venv/bin/python scripts/create_workers.py --status   # list the pool and health, create nothing
    .venv/bin/python scripts/create_workers.py --delete   # destroy every instance tagged tempo-worker

Idempotent: labels that already exist are kept. Workers get tag `tempo-worker` (what the audit's pool and
demo_reset look for), hostname = label (the worker reports it as worker_id), and your SSH key.
Needs VULTR_API_KEY, VULTR_WORKER_SNAPSHOT_ID, VULTR_SSHKEY_ID, TEMPO_WORKER_TOKEN in .env.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.audit.pool import HttpWorkerPool  # noqa: E402
from tempo.config import env, settings  # noqa: E402
from tempo.infra.vultr import VultrClient, VultrError  # noqa: E402

TAGS = ["tempo", "tempo-worker"]


def health_table(vultr: VultrClient, token: str | None) -> bool:
    workers = vultr.list_workers()
    if not workers:
        print("no instances tagged tempo-worker")
        return False
    pool = HttpWorkerPool.from_vultr(vultr, token=token) if any(w.is_active for w in workers) else None
    health = asyncio.run(pool.health()) if pool else {}
    all_ok = True
    print(f"{'label':16} {'status':8} {'power':8} {'ip':16} {'region':6} health")
    for w in workers:
        ok, detail = health.get(w.label, (False, "not active"))
        all_ok &= ok
        print(
            f"{w.label:16} {w.status:8} {w.power_status:8} {w.main_ip:16} {w.region:6} "
            f"{'OK ' if ok else 'BAD'} {detail[:90]}"
        )
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    s = settings()
    if not s.vultr.configured:
        print("VULTR_API_KEY missing")
        return 2
    token = env("TEMPO_WORKER_TOKEN")
    vultr = VultrClient.from_env()
    t0 = time.monotonic()

    if args.delete:
        for w in vultr.list_workers():
            vultr.delete_instance(w.instance_id)
            print(f"deleted {w.label} ({w.instance_id})")
        return 0
    if args.status:
        return 0 if health_table(vultr, token) else 1

    if not s.vultr.worker_snapshot_id or not s.vultr.sshkey_id:
        print("VULTR_WORKER_SNAPSHOT_ID / VULTR_SSHKEY_ID missing: run scripts/build_worker_image.py first")
        return 2
    snap = vultr.get_snapshot(s.vultr.worker_snapshot_id)
    if snap.get("status") != "complete":
        print(f"snapshot {s.vultr.worker_snapshot_id} is {snap.get('status')}, not complete")
        return 1

    existing = {w.label: w for w in vultr.list_workers()}
    wanted = [f"tempo-worker-{k}" for k in range(1, args.count + 1)]
    created = []
    for label in wanted:
        if label in existing:
            print(f"{label}: exists ({existing[label].status})")
            continue
        try:
            w = vultr.create_instance(
                label,
                region=s.vultr.region,
                plan=s.vultr.worker_plan,
                snapshot_id=s.vultr.worker_snapshot_id,
                sshkey_ids=[s.vultr.sshkey_id],
                tags=TAGS,
                hostname=label,
            )
        except VultrError as exc:
            print(f"{label}: create failed: {exc}")
            if "limit" in str(exc).lower():
                print("Vultr instance limit reached: request an increase (Billing -> Limits) or use --count")
            break
        created.append(w)
        print(f"[{time.monotonic() - t0:5.1f}s] {label}: created {w.instance_id}")

    for w in created:
        vultr.wait_active(w.instance_id, timeout=900, interval=5)
        print(f"[{time.monotonic() - t0:5.1f}s] {w.label}: active")

    # Health from this laptop, with retries: the service starts a few seconds after the box is active.
    deadline = time.monotonic() + 300
    while True:
        ok = health_table(vultr, token)
        if ok or time.monotonic() > deadline:
            break
        time.sleep(10)
        print("...retrying health")
    print(f"pool {'ready' if ok else 'NOT fully healthy'} after {time.monotonic() - t0:.0f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
