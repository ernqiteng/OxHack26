#!/usr/bin/env python3
"""Deploy one small Vultr instance, time create -> active -> SSH port open, print numbers for needs.md B4.

    .venv/bin/python scripts/time_vultr.py            # vc2-1c-1gb in VULTR_REGION, deleted afterwards
    .venv/bin/python scripts/time_vultr.py --keep --label tempo-backend --region lhr --plan vc2-1c-2gb
    .venv/bin/python scripts/time_vultr.py --account              # just print account info and the plan list

Needs VULTR_API_KEY in .env. Uses VULTR_SSHKEY_ID if set, else uploads ~/.ssh/id_ed25519.pub (or id_rsa.pub)
as "tempo-<user>" and prints the id to put in .env.
"""

from __future__ import annotations

import argparse
import getpass
import socket
import sys
import time
from pathlib import Path

from tempo.config import settings
from tempo.infra.vultr import VultrClient, VultrError


def ensure_ssh_key(vultr: VultrClient, configured_id: str | None) -> str | None:
    if configured_id:
        return configured_id
    for cand in ("id_ed25519.pub", "id_rsa.pub"):
        p = Path.home() / ".ssh" / cand
        if p.exists():
            pub = p.read_text().strip()
            for key in vultr.list_ssh_keys():
                if key.get("ssh_key", "").split()[:2] == pub.split()[:2]:
                    print(f"ssh key already on Vultr: {key['id']} ({key['name']})")
                    return key["id"]
            created = vultr.create_ssh_key(f"tempo-{getpass.getuser()}", pub)
            print(f"uploaded {p} as {created['id']}; add VULTR_SSHKEY_ID={created['id']} to .env")
            return created["id"]
    print("no ~/.ssh/id_ed25519.pub or id_rsa.pub found; instance will only have a root password")
    return None


def wait_port(ip: str, port: int, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            with socket.create_connection((ip, port), timeout=3):
                return True
        except OSError:
            time.sleep(2)
    return False


def main() -> int:
    s = settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=s.vultr.region)
    ap.add_argument("--plan", default=s.vultr.worker_plan)
    ap.add_argument("--label", default=f"tempo-timing-{int(time.time())}")
    ap.add_argument("--os", default="Ubuntu 24.04", help="substring of the OS name")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--account", action="store_true", help="print account + plans and exit")
    args = ap.parse_args()

    if not s.vultr.configured:
        print("VULTR_API_KEY missing in .env")
        return 2
    vultr = VultrClient.from_env()

    acct = vultr.account()
    print(
        f"account: {acct.get('name')} <{acct.get('email')}> "
        f"balance={acct.get('balance')} pending={acct.get('pending_charges')}"
    )
    if args.account:
        plans = vultr.list_plans("vc2")
        for p in plans[:6]:
            print(
                f"  {p['id']:14s} {p['vcpu_count']}vcpu {p['ram']}MB ${p['monthly_cost']}/mo "
                f"regions={len(p.get('locations', []))}"
            )
        gpu = vultr.list_plans("vcg")
        print(f"  GPU plans visible: {len(gpu)}" + (f" e.g. {gpu[0]['id']}" if gpu else ""))
        print("instance limit is not exposed by the API: check Billing -> Limits in the portal")
        return 0

    sshkey = ensure_ssh_key(vultr, s.vultr.sshkey_id)
    os_id = vultr.find_os_id(args.os)
    print(f"creating {args.plan} in {args.region} (os_id={os_id}) label={args.label}")

    inst = None
    t0 = time.monotonic()
    try:
        inst = vultr.create_instance(
            args.label,
            region=args.region,
            plan=args.plan,
            os_id=os_id,
            sshkey_ids=[sshkey] if sshkey else None,
            tags=["tempo", "timing"],
        )
        t_create = time.monotonic() - t0
        print(f"[{t_create:5.1f}s] POST /instances -> {inst.instance_id} status={inst.status}")

        def on_status(w, elapsed):
            print(
                f"[{t_create + elapsed:5.1f}s] status={w.status} power={w.power_status} "
                f"server={w.server_status} ip={w.main_ip}"
            )

        active = vultr.wait_active(inst.instance_id, timeout=900, interval=5, on_status=on_status)
        t_active = time.monotonic() - t0
        print(f"[{t_active:5.1f}s] active ip={active.main_ip}")

        ssh_ok = wait_port(active.main_ip, 22, 600)
        t_ssh = time.monotonic() - t0
        print(f"[{t_ssh:5.1f}s] ssh port {'open' if ssh_ok else 'NOT open'}")

        print()
        print("Paste into docs/needs.md B4:")
        print(
            f"  {args.plan} in {args.region}: create {t_create:.0f}s, active {t_active:.0f}s, "
            f"SSH-able {t_ssh:.0f}s"
            f"  ({time.strftime('%Y-%m-%d %H:%M')})"
        )
        if args.keep:
            print(f"kept {inst.instance_id} at {active.main_ip}: ssh root@{active.main_ip}")
        return 0
    except VultrError as exc:
        print(f"FAILED after {time.monotonic() - t0:.0f}s: {exc}")
        return 1
    finally:
        if inst is not None and not args.keep:
            vultr.delete_instance(inst.instance_id)
            print(f"deleted {inst.instance_id}")
        vultr.close()


if __name__ == "__main__":
    sys.exit(main())
