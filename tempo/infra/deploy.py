"""Helpers for building Vultr boxes from this laptop: SSH key upload, ssh/rsync, .env updates.

Owner: Ayo. Used by scripts/build_worker_image.py.
"""

from __future__ import annotations

import getpass
import re
import subprocess
import time
from pathlib import Path

from tempo.config import REPO_ROOT

ENV_FILE = REPO_ROOT / ".env"
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]
RSYNC_EXCLUDES = [
    ".env",
    ".venv/",
    ".git/",
    "node_modules/",
    ".next/",
    "out/",  # the static site exports go to /var/www/tempo separately (rsync_dir)
    "__pycache__/",
    "*.pyc",
    "*.egg-info/",
    "models/",
    "data/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".DS_Store",
]


def find_public_key(preferred: str | None = None) -> Path:
    candidates = [Path(preferred).expanduser()] if preferred else []
    candidates += [Path.home() / ".ssh" / n for n in ("id_ed25519.pub", "tempo_vultr.pub", "id_rsa.pub")]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("no SSH public key in ~/.ssh; create one with: ssh-keygen -t ed25519")


def private_key_for(pub: Path) -> Path:
    return pub.with_suffix("")


def ensure_ssh_key(vultr, pub: Path) -> str:
    """Return the Vultr id of this public key, uploading it if Vultr doesn't have it yet."""
    text = pub.read_text().strip()
    for key in vultr.list_ssh_keys():
        if key.get("ssh_key", "").split()[:2] == text.split()[:2]:
            return key["id"]
    return vultr.create_ssh_key(f"tempo-{getpass.getuser()}", text)["id"]


def set_env_var(name: str, value: str, path: Path = ENV_FILE) -> None:
    """Set NAME=value in .env, replacing an existing line (even a blank one) or appending."""
    text = path.read_text() if path.exists() else ""
    line = f"{name}={value}"
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.M)
    text = pattern.sub(line, text, count=1) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text)


def ssh(ip: str, key: Path, command: str, *, timeout: int = 1800, env: dict | None = None) -> str:
    prefix = " ".join(f"{k}={v}" for k, v in (env or {}).items())
    full = f"{prefix} {command}".strip()
    r = subprocess.run(
        ["ssh", "-i", str(key), *SSH_OPTS, f"root@{ip}", full],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ssh {ip} '{command}' failed ({r.returncode}): {(r.stderr or r.stdout)[-800:]}")
    return r.stdout


def wait_ssh(ip: str, key: Path, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            ssh(ip, key, "cloud-init status --wait >/dev/null 2>&1; echo ready", timeout=240)
            return
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(5)
    raise TimeoutError(f"no SSH login to {ip} within {timeout:.0f}s: {last[-300:]}")


def rsync_dir(src: Path, ip: str, key: Path, dest: str, excludes: list[str] = ()) -> None:
    """Mirror the contents of `src` into `dest` on the box (trailing slashes: contents, not the folder)."""
    ssh(ip, key, f"mkdir -p {dest}")
    cmd = [
        "rsync",
        "-az",
        "--delete",
        *sum((["--exclude", e] for e in excludes), []),
        "-e",
        f"ssh -i {key} {' '.join(SSH_OPTS)}",
        f"{src}/",
        f"root@{ip}:{dest.rstrip('/')}/",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"rsync {src} to {ip} failed: {r.stderr[-500:]}")


def rsync_repo(ip: str, key: Path, dest: str = "/opt/tempo/") -> None:
    rsync_dir(REPO_ROOT, ip, key, dest, RSYNC_EXCLUDES)
