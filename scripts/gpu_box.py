"""One Vultr GPU box (NVIDIA A16, London) for the neural-net walk-forward. Owner: Girik.

    python scripts/gpu_box.py add-key ~/.ssh/tempo_gpu.pub   # register this laptop's key as tempo-girik-gpu
    python scripts/gpu_box.py create                         # one A16 in lhr; waits for SSH; starts billing
    python scripts/gpu_box.py check                          # nvidia-smi + torch.cuda on the box
    python scripts/gpu_box.py run                            # tempo_nn job on the box -> data/gpu_out
    python scripts/gpu_box.py run-final                      # final 100-week job -> data/gpu_out_final
    python scripts/gpu_box.py status                         # uptime and cost so far
    python scripts/gpu_box.py delete                         # delete it (do this whenever it is idle)

Safety: every command only sees instances that carry the tag `tempo-gpu` AND a label starting `tempo-gpu-`.
The backend (`tempo-backend`) and the workers (`tempo-worker-*`) can never match, so this script cannot
create over, inspect or delete them. `create` refuses if a GPU box already exists (no accidental second box).

Billing runs from create until delete, even when the box is stopped: never leave it idle.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.infra.deploy import ssh, wait_ssh  # noqa: E402

PLAN = "vcg-a16-6c-60g-16vram"  # 6 vCPU, 60 GB RAM, one NVIDIA A16 (16 GB)
HOURLY_USD = 0.471  # GET /v2/plans?type=all on 25 Oct 2026 (the type=vcg filter omits A16 plans)
REGION = "lhr"
OS_ID = 1743  # Ubuntu 22.04 LTS x64; first check on the box is nvidia-smi
LABEL = "tempo-gpu-1"
TAG = "tempo-gpu"
KEY_NAME = "tempo-girik-gpu"
KEY_PATH = Path.home() / ".ssh" / "tempo_gpu"


def is_gpu_box(inst: dict) -> bool:
    """True only for our GPU box: tag AND label prefix, so backend and workers can never match."""
    tags = set(inst.get("tags") or []) | ({inst["tag"]} if inst.get("tag") else set())
    return TAG in tags and str(inst.get("label", "")).startswith("tempo-gpu-")


def gpu_boxes(client) -> list[dict]:
    return [i for i in client.list_instances(tag=TAG) if is_gpu_box(i)]


def create_body(sshkey_id: str) -> dict:
    """The exact POST /v2/instances body (kept here so the test pins it)."""
    return {
        "label": LABEL,
        "region": REGION,
        "plan": PLAN,
        "os_id": OS_ID,
        "sshkey_ids": [sshkey_id],
        "tags": ["tempo", TAG],
        "hostname": LABEL,
    }


def key_id(client) -> str:
    for k in client.list_ssh_keys():
        if k.get("name") == KEY_NAME:
            return k["id"]
    raise SystemExit(f"no Vultr SSH key named {KEY_NAME}: run `gpu_box.py add-key {KEY_PATH}.pub` first")


def add_key(client, pub_path: Path) -> str:
    for k in client.list_ssh_keys():
        if k.get("name") == KEY_NAME:
            print(f"key {KEY_NAME} already on the account")
            return k["id"]
    created = client.create_ssh_key(KEY_NAME, pub_path.read_text())
    print(f"added SSH key {KEY_NAME} to the Vultr account")
    return created["id"]


def create(client, *, wait=True) -> dict:
    existing = gpu_boxes(client)
    if existing:
        raise SystemExit(
            f"a GPU box already exists ({existing[0]['label']}, {existing[0].get('main_ip')}); "
            "not creating another"
        )
    body = create_body(key_id(client))
    label = body.pop("label")
    box = client.create_instance(label, **body)
    started = datetime.now(UTC)
    print(f"created {label} ({PLAN}, {REGION}): billing ${HOURLY_USD}/h since {started:%H:%M:%S} UTC")
    if not wait:
        return {"id": box.instance_id, "label": label}
    box = client.wait_active(
        box.instance_id,
        timeout=900,
        on_status=lambda w, s: print(f"  +{s:4.0f}s {w.status}/{w.power_status}/{w.server_status}"),
    )
    print(f"  active at {box.main_ip}; waiting for SSH")
    wait_ssh(box.main_ip, KEY_PATH, timeout=600)
    print(f"ready: ssh -i {KEY_PATH} root@{box.main_ip}")
    return {"id": box.instance_id, "label": label, "ip": box.main_ip}


def only_box(client) -> dict:
    boxes = gpu_boxes(client)
    if not boxes:
        raise SystemExit("no GPU box exists")
    if len(boxes) > 1:
        raise SystemExit(
            f"{len(boxes)} GPU boxes exist; delete the extras first: {[b['label'] for b in boxes]}"
        )
    return boxes[0]


def cuda_wheel_index(nvidia_smi_output: str) -> str:
    """PyTorch wheel index matching the driver's CUDA version shown by nvidia-smi."""
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", nvidia_smi_output)
    if not m:
        raise ValueError("nvidia-smi shows no CUDA version")
    version = (int(m.group(1)), int(m.group(2)))
    for need, tag in (((12, 4), "cu124"), ((12, 1), "cu121"), ((11, 8), "cu118")):
        if version >= need:
            return f"https://download.pytorch.org/whl/{tag}"
    raise ValueError(f"driver CUDA {version} is older than any supported PyTorch wheel")


def check(client) -> None:
    ip = only_box(client)["main_ip"]
    try:
        smi = ssh(ip, KEY_PATH, "nvidia-smi", timeout=60)
    except RuntimeError as exc:
        raise SystemExit(
            f"FAIL: nvidia-smi did not run on the box ({exc}). Delete it: gpu_box.py delete"
        ) from exc
    print(smi)
    index = cuda_wheel_index(smi)
    print(f"installing torch from {index} (a few minutes)")
    ssh(
        ip,
        KEY_PATH,
        "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq"
        " && apt-get install -y -qq python3-venv >/dev/null"
        f" && python3 -m venv /opt/gpu-venv && /opt/gpu-venv/bin/pip install -q torch --index-url {index}",
        timeout=1800,
    )
    out = ssh(
        ip,
        KEY_PATH,
        '/opt/gpu-venv/bin/python -c "import torch; print(torch.cuda.is_available(), '
        'torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"',
        timeout=120,
    )
    print("torch:", out.strip())


REPO = Path(__file__).resolve().parents[1]
REMOTE = "/opt/tempo-gpu"


JOBS = {
    # name: (script and args on the box, result files copied back, extra local files sent to data/). run-final
    # also pins the box's data/model libraries to this laptop's versions (PINNED), so the recompute of tempo
    # and tempo_lp is a like-for-like check and the feature cache unpickles.
    "run": ("scripts/backtest_nn.py --frames data/frames --out out --device cuda",
            ["results_tempo_nn.parquet", "gpu_runs.json"], []),
    "run-final": ("scripts/backtest_nn_final.py --frames data/frames --out out --device cuda"
                  " --features data/frames_features.pkl",
                  ["results_final.parquet", "timing_final.json"], [REPO / "data" / "frames_features.pkl"]),
}  # fmt: skip


PINNED = ["pandas", "numpy", "pyarrow", "lightgbm", "scikit-learn", "scipy", "highspy"]


def pins() -> str:
    from importlib.metadata import version

    return " ".join(f"{p}=={version(p)}" for p in PINNED)


def run_job(client, frames_dir: Path, out_dir: Path, job: str = "run") -> None:
    """A job on the box: committed code (git archive HEAD), the parquet frames (+ the job's extra files),
    Python 3.12 + CUDA torch, the job's script on cuda, results copied back. The box never gets the DSN."""
    import subprocess

    from tempo.infra.deploy import SSH_OPTS

    ip = only_box(client)["main_ip"]
    target = f"root@{ip}"
    base = ["-i", str(KEY_PATH), *SSH_OPTS]
    print("pushing committed code (git archive HEAD)")
    archive = subprocess.Popen(["git", "archive", "HEAD"], cwd=REPO, stdout=subprocess.PIPE)
    subprocess.run(
        ["ssh", *base, target, f"mkdir -p {REMOTE} && tar -x -C {REMOTE}"], stdin=archive.stdout, check=True
    )
    archive.wait()
    print("copying frames")
    ssh(ip, KEY_PATH, f"mkdir -p {REMOTE}/data/frames {REMOTE}/out")
    command, results, extras = JOBS[job]
    files = [str(p) for p in sorted(frames_dir.glob("*.parquet"))]
    subprocess.run(["scp", *base, *files, f"{target}:{REMOTE}/data/frames/"], check=True, capture_output=True)
    if extras:
        subprocess.run(
            ["scp", *base, *map(str, extras), f"{target}:{REMOTE}/data/"], check=True, capture_output=True
        )
    index = cuda_wheel_index(ssh(ip, KEY_PATH, "nvidia-smi", timeout=60))
    print("installing Python 3.12, CUDA torch and the repo (a few minutes)")
    ssh(
        ip,
        KEY_PATH,
        # Idempotent: a rerun on the same box skips what the first run installed.
        "if [ ! -x /opt/py312/bin/python ]; then export DEBIAN_FRONTEND=noninteractive;"
        " apt-get update -qq; apt-get install -y -qq python3-venv >/dev/null"
        " && python3 -m venv /opt/uv-venv && /opt/uv-venv/bin/pip install -q uv"
        " && /opt/uv-venv/bin/uv venv -q -p 3.12 /opt/py312"
        f" && /opt/uv-venv/bin/uv pip install -q --python /opt/py312/bin/python torch --index-url {index}; fi"
        f" && /opt/uv-venv/bin/uv pip install -q --python /opt/py312/bin/python -e {REMOTE}",
        timeout=2400,
    )
    if job == "run-final":
        print(f"pinning {pins()}")
        ssh(
            ip,
            KEY_PATH,
            f"/opt/uv-venv/bin/uv pip install -q --python /opt/py312/bin/python {pins()}",
            timeout=900,
        )
    print(f"running {command}")
    out = ssh(ip, KEY_PATH, f"cd {REMOTE} && /opt/py312/bin/python -u {command}", timeout=3600)
    print(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "scp",
            *base,
            *(f"{target}:{REMOTE}/out/{name}" for name in results),
            str(out_dir),
        ],
        check=True,
        capture_output=True,
    )
    print(f"results copied to {out_dir}. Now delete the box: gpu_box.py delete")


def status(client, now: datetime | None = None) -> None:
    boxes = gpu_boxes(client)
    if not boxes:
        print("no GPU box exists: nothing is billing")
        return
    now = now or datetime.now(UTC)
    for b in boxes:
        created = datetime.fromisoformat(b["date_created"].replace("Z", "+00:00"))
        hours = (now - created).total_seconds() / 3600
        print(
            f"{b['label']} {b.get('main_ip')} {b.get('status')}: "
            f"up {hours:.2f} h, about ${hours * HOURLY_USD:.2f} so far"
        )


def delete(client, *, sleep=time.sleep) -> None:
    boxes = gpu_boxes(client)
    if not boxes:
        print("no GPU box exists: nothing to delete")
        return
    for b in boxes:
        assert is_gpu_box(b)  # never reaches backend or workers
        client.delete_instance(b["id"])
        print(f"deleted {b['label']} ({b.get('main_ip')})")
    for _ in range(30):
        if not gpu_boxes(client):
            print("confirmed: no GPU box left, billing stopped")
            return
        sleep(2)
    raise SystemExit("delete sent but the box still lists; check the Vultr console")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("add-key")
    k.add_argument("pub", type=Path)
    for name in ("create", "check", "status", "delete"):
        sub.add_parser(name)
    for job, out in (("run", "gpu_out"), ("run-final", "gpu_out_final")):
        r = sub.add_parser(job)
        r.add_argument("--frames", type=Path, default=REPO / "data" / "frames")
        r.add_argument("--out", type=Path, default=REPO / "data" / out)
    a = ap.parse_args()

    from tempo.infra.vultr import VultrClient

    client = VultrClient.from_env()
    {
        "add-key": lambda: add_key(client, a.pub.expanduser()),
        "create": lambda: create(client),
        "check": lambda: check(client),
        "status": lambda: status(client),
        "delete": lambda: delete(client),
        "run": lambda: run_job(client, a.frames, a.out),
        "run-final": lambda: run_job(client, a.frames, a.out, job="run-final"),
    }[a.cmd]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
