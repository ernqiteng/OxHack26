#!/usr/bin/env python3
"""Create the backend box (dashboard + poller) in London and deploy the repo to it.

    .venv/bin/python scripts/create_backend.py           # create if missing, deploy, start the dashboard
    .venv/bin/python scripts/create_backend.py --deploy  # redeploy code + .env to the existing box, restart
    .venv/bin/python scripts/create_backend.py --delete

Box: label `tempo-backend`, VULTR_BACKEND_REGION (default lhr), VULTR_BACKEND_PLAN (default vc2-1c-2gb),
Ubuntu 24.04, your SSH key, tags tempo + tempo-backend (never tempo-worker). The laptop's .env is copied to
/opt/tempo/.env, so the box sees the same Tiger, Vultr and worker-token settings. Dashboard on port 8501.
The poller unit is installed but only enabled once scripts/poll.py exists (Girik's Phase 2).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from tempo.config import REPO_ROOT, env, settings  # noqa: E402
from tempo.infra.deploy import SSH_OPTS, find_public_key, private_key_for, rsync_repo, ssh, wait_ssh  # noqa: E402
from tempo.infra.vultr import VultrClient  # noqa: E402

LABEL = "tempo-backend"


def step(t0: float, msg: str) -> None:
    print(f"[{time.monotonic() - t0:6.1f}s] {msg}", flush=True)


def find_backend(vultr: VultrClient):
    for inst in vultr.list_instances():
        if inst.get("label") == LABEL:
            from tempo.infra.vultr import Worker

            return Worker.from_api(inst)
    return None


def deploy(ip: str, key: Path, t0: float, *, enable_poller: bool) -> None:
    rsync_repo(ip, key)
    subprocess.run(
        ["scp", "-i", str(key), *SSH_OPTS, str(REPO_ROOT / ".env"), f"root@{ip}:/opt/tempo/.env"],
        check=True,
        capture_output=True,
    )
    step(t0, "repo and .env copied, running bootstrap (first run installs for a few minutes)")
    out = ssh(ip, key, "ROLE=backend bash /opt/tempo/deploy/bootstrap.sh")
    print("         " + out.strip().splitlines()[-1])
    # The tempo user exists only after bootstrap, so lock the .env down now.
    ssh(ip, key, "chown tempo:tempo /opt/tempo/.env && chmod 600 /opt/tempo/.env")
    models = sorted((REPO_ROOT / "models").glob("lgbm_*.joblib")) + [REPO_ROOT / "models" / "training.json"]
    models = [m for m in models if m.exists()]
    if len(models) >= 3:
        ssh(ip, key, "mkdir -p /opt/tempo/models && chown tempo:tempo /opt/tempo/models")
        subprocess.run(
            ["scp", "-i", str(key), *SSH_OPTS, *map(str, models), f"root@{ip}:/opt/tempo/models/"],
            check=True,
            capture_output=True,
        )
        ssh(ip, key, "chown -R tempo:tempo /opt/tempo/models")
        step(t0, f"copied {len(models)} model files to /opt/tempo/models")
    units = (
        "tempo-dashboard"
        + (" tempo-poller" if enable_poller else "")
        + (" tempo-decider" if len(models) >= 3 else "")
    )
    ssh(ip, key, f"systemctl enable --now {units} && systemctl restart {units}")
    deadline = time.monotonic() + 120
    while True:
        try:
            if httpx.get(f"http://{ip}:8501/_stcore/health", timeout=5).text.strip() == "ok":
                break
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() > deadline:
            raise TimeoutError("dashboard did not answer /_stcore/health within 120 s")
        time.sleep(3)
    step(t0, f"dashboard up: http://{ip}:8501")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deploy", action="store_true", help="redeploy to the existing box")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--region", default=env("VULTR_BACKEND_REGION", "lhr"))
    ap.add_argument("--plan", default=env("VULTR_BACKEND_PLAN", "vc2-1c-2gb"))
    args = ap.parse_args()

    s = settings()
    if not s.vultr.configured or not s.vultr.sshkey_id:
        print("VULTR_API_KEY / VULTR_SSHKEY_ID missing (run build_worker_image.py --key-only for the key)")
        return 2
    if not s.database_url:
        print("TEMPO_DATABASE_URL missing: the dashboard on the box would only show synthetic data")
        return 2
    vultr = VultrClient.from_env()
    t0 = time.monotonic()
    key = private_key_for(find_public_key())
    box = find_backend(vultr)

    if args.delete:
        if box:
            vultr.delete_instance(box.instance_id)
            print(f"deleted {LABEL} ({box.instance_id})")
        return 0

    poller_ready = (REPO_ROOT / "scripts/poll.py").read_text().count("\n") > 10
    if box is None:
        if args.deploy:
            print("no backend box to deploy to")
            return 1
        box = vultr.create_instance(
            LABEL,
            region=args.region,
            plan=args.plan,
            os_id=vultr.find_os_id("Ubuntu 24.04"),
            sshkey_ids=[s.vultr.sshkey_id],
            tags=["tempo", "tempo-backend"],
            hostname=LABEL,
        )
        step(t0, f"created {LABEL} ({box.instance_id}) in {args.region}, waiting for boot")
        box = vultr.wait_active(box.instance_id, timeout=900, interval=5)
        step(t0, f"active at {box.main_ip}, waiting for SSH")
        wait_ssh(box.main_ip, key, timeout=420)
    else:
        print(f"{LABEL} exists at {box.main_ip} ({box.status})")
    deploy(box.main_ip, key, t0, enable_poller=poller_ready)
    if not poller_ready:
        print("         poller not enabled: scripts/poll.py is still a stub (Girik's Phase 2)")
    if not (REPO_ROOT / "models" / "lgbm_p50.joblib").exists():
        print("         decider not enabled: no model in models/ (run scripts/train.py first)")
    print(f"\nssh -i {key} root@{box.main_ip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
