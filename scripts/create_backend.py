#!/usr/bin/env python3
"""Create the backend box in London and deploy the repo and the two websites to it.

    .venv/bin/python scripts/create_backend.py           # create if missing, deploy everything, start units
    .venv/bin/python scripts/create_backend.py --deploy  # redeploy code, .env and sites to the existing box
    .venv/bin/python scripts/create_backend.py --deploy --no-sites   # skip the npm builds
    .venv/bin/python scripts/create_backend.py --delete

Box: label `tempo-backend`, VULTR_BACKEND_REGION (default lhr), VULTR_BACKEND_PLAN (default vc2-1c-2gb),
Ubuntu 24.04, your SSH key, tags tempo + tempo-backend (never tempo-worker). The laptop's .env is copied to
/opt/tempo/.env, so the box sees the same Tiger, Vultr and worker-token settings.

On the box: Streamlit on :8501, and nginx on :80 serving the presentation website at /, the pitch dashboard
at /app/ and the JSON API (tempo-api, uvicorn on 127.0.0.1:8000) at /api/. Both sites are built here with
npm (the 2 GB box has no Node) and their static exports are copied to /var/www/tempo.
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
from tempo.infra.deploy import (  # noqa: E402
    SSH_OPTS,
    find_public_key,
    private_key_for,
    rsync_dir,
    rsync_repo,
    ssh,
    wait_ssh,
)
from tempo.infra.vultr import VultrClient  # noqa: E402

LABEL = "tempo-backend"
# (folder, build-time env, where nginx serves it from). The pitch site is built for /app/ and calls the API on
# the same origin; the presentation site's "Open the app" button points at /app/ by default.
SITES = (
    ("presentation", {}, "/var/www/tempo/presentation/"),
    ("pitch", {"NEXT_PUBLIC_BASE_PATH": "/app", "NEXT_PUBLIC_TEMPO_API": ""}, "/var/www/tempo/app/"),
)


def step(t0: float, msg: str) -> None:
    print(f"[{time.monotonic() - t0:6.1f}s] {msg}", flush=True)


def find_backend(vultr: VultrClient):
    for inst in vultr.list_instances():
        if inst.get("label") == LABEL:
            from tempo.infra.vultr import Worker

            return Worker.from_api(inst)
    return None


def build_sites(t0: float) -> list[tuple[Path, str]]:
    """npm build both static sites on this machine. Returns (export dir, destination on the box) pairs."""
    import os
    import shutil

    if not shutil.which("npm"):
        raise RuntimeError("npm not found: install Node 20+ or pass --no-sites")
    built = []
    for folder, extra_env, dest in SITES:
        root = REPO_ROOT / folder
        if not (root / "node_modules").exists():
            subprocess.run(["npm", "ci", "--no-audit"], cwd=root, check=True, capture_output=True)
        out = root / "out"
        shutil.rmtree(out, ignore_errors=True)
        r = subprocess.run(
            ["npm", "run", "build"], cwd=root, env={**os.environ, **extra_env}, capture_output=True, text=True
        )
        if r.returncode != 0 or not (out / "index.html").exists():
            raise RuntimeError(f"{folder}: npm run build failed:\n{(r.stderr or r.stdout)[-1500:]}")
        step(t0, f"built {folder}/ -> {out.relative_to(REPO_ROOT)} ({sum(1 for _ in out.rglob('*'))} files)")
        built.append((out, dest))
    return built


def check_http(url: str, ok, what: str, timeout: float = 120):
    """Poll `url` until `ok(response)` is true; returns that response."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            r = httpx.get(url, timeout=5)
            if ok(r):
                return r
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
        if time.monotonic() > deadline:
            raise TimeoutError(f"{what} ({url}) not healthy within {timeout:.0f} s: {last}")
        time.sleep(3)


def deploy(ip: str, key: Path, t0: float, *, enable_poller: bool, sites: bool = False) -> None:
    built = build_sites(t0) if sites else []
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
    model_dir = REPO_ROOT / "models"
    models = sorted(model_dir.glob("lgbm_*.joblib"))
    extras = [m for m in sorted(model_dir.glob("*.json")) + sorted(model_dir.glob("*.parquet")) if m.exists()]
    if models or extras:
        ssh(ip, key, "mkdir -p /opt/tempo/models && chown tempo:tempo /opt/tempo/models")
        subprocess.run(
            ["scp", "-i", str(key), *SSH_OPTS, *map(str, models + extras), f"root@{ip}:/opt/tempo/models/"],
            check=True,
            capture_output=True,
        )
        ssh(ip, key, "chown -R tempo:tempo /opt/tempo/models")
        step(t0, f"copied {len(models) + len(extras)} files to /opt/tempo/models (model, replay week)")
    for out, dest in built:
        rsync_dir(out, ip, key, dest)
    if built:
        ssh(ip, key, "chown -R www-data:www-data /var/www/tempo")
        step(t0, f"copied {len(built)} site exports to /var/www/tempo")
    units = (
        "tempo-dashboard tempo-api"
        + (" tempo-poller" if enable_poller else "")
        + (" tempo-decider" if len(models) >= 3 else "")
    )
    ssh(ip, key, f"systemctl enable --now {units} && systemctl restart {units} nginx")
    check_http(f"http://{ip}:8501/_stcore/health", lambda r: r.text.strip() == "ok", "Streamlit")
    step(t0, f"dashboard up: http://{ip}:8501")
    api = check_http(
        f"http://{ip}/api/status", lambda r: r.status_code == 200 and r.json().get("source"), "API"
    )
    source = api.json()["source"]
    step(t0, f"api up: http://{ip}/api/status (source: {source})")
    if source != "tiger":
        print("         WARNING: the API is not reading Tiger; check TEMPO_DATABASE_URL on the box")
    if built:
        html = lambda r: r.status_code == 200 and "<html" in r.text  # noqa: E731
        check_http(f"http://{ip}/", html, "presentation site")
        check_http(f"http://{ip}/app/", html, "pitch dashboard")
        check_http(f"http://{ip}/app/timing", lambda r: r.status_code == 200, "pitch dashboard routes")
        step(t0, f"sites up: http://{ip}/ and http://{ip}/app/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deploy", action="store_true", help="redeploy to the existing box")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--no-sites", action="store_true", help="don't build and copy the two websites")
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
    deploy(box.main_ip, key, t0, enable_poller=poller_ready, sites=not args.no_sites)
    if not poller_ready:
        print("         poller not enabled: scripts/poll.py is still a stub (Girik's Phase 2)")
    if not (REPO_ROOT / "models" / "lgbm_p50.joblib").exists():
        print("         decider not enabled: no model in models/ (run scripts/train.py first)")
    print(f"\nssh -i {key} root@{box.main_ip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
