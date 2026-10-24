#!/usr/bin/env python3
"""Build the Vultr worker image and fill in .env:
VULTR_SSHKEY_ID, TEMPO_WORKER_TOKEN and VULTR_WORKER_SNAPSHOT_ID.

    .venv/bin/python scripts/build_worker_image.py            # full build, deletes the build box at the end
    .venv/bin/python scripts/build_worker_image.py --keep     # keep the build box (for debugging over SSH)
    .venv/bin/python scripts/build_worker_image.py --key-only # only upload the SSH key, set VULTR_SSHKEY_ID

Steps: upload ~/.ssh/id_ed25519.pub (once) -> create one vc2-1c-1gb box in VULTR_REGION (ewr, next to Tiger
us-east-1) -> rsync this repo to /opt/tempo (the GitHub repo is private) -> deploy/bootstrap.sh as a worker ->
check /health and token auth from this laptop -> snapshot -> wait until complete -> delete the build box.

The build box is tagged 'tempo-image', not 'tempo-worker', so the audit never dispatches to it.
Costs: one small instance for ~10 minutes plus snapshot storage, both cents.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from tempo.config import env, settings  # noqa: E402
from tempo.infra.deploy import (  # noqa: E402
    ensure_ssh_key,
    find_public_key,
    private_key_for,
    rsync_repo,
    set_env_var,
    ssh,
    wait_ssh,
)
from tempo.infra.vultr import VultrClient, VultrError  # noqa: E402


def step(t0: float, msg: str) -> None:
    print(f"[{time.monotonic() - t0:6.1f}s] {msg}", flush=True)


def check_worker(ip: str, token: str) -> None:
    base = f"http://{ip}:8000"
    deadline = time.monotonic() + 120
    while True:
        try:
            h = httpx.get(f"{base}/health", timeout=5).json()
            break
        except Exception:  # noqa: BLE001
            if time.monotonic() > deadline:
                raise
            time.sleep(3)
    assert h.get("ok") and h.get("auth"), f"unexpected /health: {h}"
    body = {"database_url": "postgres://x:y@127.0.0.1:1/x", "decision_id": 1, "shift": 0, "run_id": "probe"}
    no_auth = httpx.post(f"{base}/replay", json=body, timeout=15)
    assert no_auth.status_code == 401, f"/replay without token returned {no_auth.status_code}"
    authed = httpx.post(f"{base}/replay", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert authed.status_code == 500 and "cannot connect" in authed.text, f"authed probe: {authed.text[:200]}"
    print(f"         /health {h}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="keep the build box afterwards")
    ap.add_argument("--key-only", action="store_true", help="only upload the SSH key and set VULTR_SSHKEY_ID")
    ap.add_argument("--pubkey", help="public key file (default ~/.ssh/id_ed25519.pub)")
    args = ap.parse_args()

    s = settings()
    if not s.vultr.configured:
        print("VULTR_API_KEY missing in .env")
        return 2
    t0 = time.monotonic()
    vultr = VultrClient.from_env()
    try:
        vultr.account()
    except VultrError as exc:
        if "Unauthorized IP" in str(exc):
            print(f"Vultr refused this machine's IP: {exc}\nAdd it under Account -> API -> Access Control.")
            return 2
        raise

    pub = find_public_key(args.pubkey)
    key_id = ensure_ssh_key(vultr, pub)
    set_env_var("VULTR_SSHKEY_ID", key_id)
    step(t0, f"SSH key {pub.name} is Vultr key {key_id} (VULTR_SSHKEY_ID set in .env)")
    if args.key_only:
        return 0

    token = env("TEMPO_WORKER_TOKEN") or secrets.token_urlsafe(32)
    set_env_var("TEMPO_WORKER_TOKEN", token)
    priv = private_key_for(pub)

    inst = None
    try:
        label = f"tempo-image-{int(time.time())}"
        inst = vultr.create_instance(
            label,
            region=s.vultr.region,
            plan=s.vultr.worker_plan,
            os_id=vultr.find_os_id("Ubuntu 24.04"),
            sshkey_ids=[key_id],
            tags=["tempo", "tempo-image"],
            hostname="tempo-worker",
        )
        step(t0, f"created {label} ({inst.instance_id}) in {s.vultr.region}, waiting for it to boot")
        inst = vultr.wait_active(inst.instance_id, timeout=900, interval=5)
        step(t0, f"active at {inst.main_ip}, waiting for SSH")
        wait_ssh(inst.main_ip, priv, timeout=420)
        step(t0, "SSH ok, copying the repo")
        rsync_repo(inst.main_ip, priv)
        step(t0, "repo copied, running bootstrap (pip install takes a few minutes)")
        out = ssh(
            inst.main_ip,
            priv,
            "ROLE=worker bash /opt/tempo/deploy/bootstrap.sh",
            env={"TEMPO_WORKER_TOKEN": token},
        )
        print("         " + out.strip().splitlines()[-1])
        check_worker(inst.main_ip, token)
        step(t0, "worker healthy from this laptop, token enforced")

        ssh(inst.main_ip, priv, "systemctl is-enabled tempo-worker && cloud-init clean --logs || true")
        snap = vultr.create_snapshot(inst.instance_id, f"tempo-worker {time.strftime('%Y-%m-%d %H:%M')}")
        step(t0, f"snapshot {snap['id']} started, waiting for it to complete")
        deadline = time.monotonic() + 1800
        while True:
            snap = vultr.get_snapshot(snap["id"])
            if snap.get("status") == "complete":
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"snapshot {snap['id']} still {snap.get('status')} after 30 min")
            time.sleep(15)
        set_env_var("VULTR_WORKER_SNAPSHOT_ID", snap["id"])
        step(t0, f"snapshot complete, VULTR_WORKER_SNAPSHOT_ID={snap['id']} set in .env")
        return 0
    except Exception as exc:  # noqa: BLE001
        step(t0, f"FAILED: {exc}")
        if inst is not None and not args.keep:
            print(f"         rerun with --keep to debug: ssh -i {priv} root@{inst.main_ip}")
        return 1
    finally:
        if inst is not None and not args.keep:
            vultr.delete_instance(inst.instance_id)
            step(t0, f"deleted build box {inst.instance_id}")
        elif inst is not None:
            step(t0, f"kept build box: ssh -i {priv} root@{inst.main_ip}")
        vultr.close()


if __name__ == "__main__":
    sys.exit(main())
