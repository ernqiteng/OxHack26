"""Gate 0: fork the primary Tiger service via REST, time it until READY, then delete the fork.

Usage:
    python scripts/time_fork.py            # fork_strategy NOW
    python scripts/time_fork.py LAST_SNAPSHOT
    python scripts/time_fork.py NOW --keep # don't delete the fork afterwards

Reads TIGERDATA_PROJECT_ID, TIGERDATA_ACCESS_KEY, TIGERDATA_SECRET_KEY,
TIGER_PRIMARY_SERVICE_ID from the environment or from .env in the repo root.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://console.cloud.tigerdata.com/public/api/v1"


def load_env():
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def api(method, path, body=None):
    token = base64.b64encode(
        f"{os.environ['TIGERDATA_ACCESS_KEY']}:{os.environ['TIGERDATA_SECRET_KEY']}".encode()
    ).decode()
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()}")


def main():
    load_env()
    strategy = next((a for a in sys.argv[1:] if not a.startswith("--")), "NOW")
    keep = "--keep" in sys.argv
    project = os.environ["TIGERDATA_PROJECT_ID"]
    parent = os.environ["TIGER_PRIMARY_SERVICE_ID"]

    status = api("GET", f"/projects/{project}/services/{parent}").get("status")
    print(f"parent {parent} status: {status}")

    t0 = time.monotonic()
    fork = api(
        "POST",
        f"/projects/{project}/services/{parent}/forkService",
        {"fork_strategy": strategy, "name": f"gate0-timing-{int(time.time())}", "environment_tag": "DEV"},
    )
    t_accepted = time.monotonic() - t0
    fork_id = fork["service_id"]
    print(f"fork {fork_id} accepted in {t_accepted:.1f}s, status {fork.get('status')}")

    while True:
        svc = api("GET", f"/projects/{project}/services/{fork_id}")
        if svc.get("status") == "READY":
            break
        time.sleep(2)
    t_ready = time.monotonic() - t0
    ep = svc.get("endpoint", {})
    print(f"fork READY after {t_ready:.1f}s  ({strategy})  host={ep.get('host')} port={ep.get('port')}")

    if keep:
        print(f"kept fork; initial_password={fork.get('initial_password')}")
    else:
        api("DELETE", f"/projects/{project}/services/{fork_id}")
        print("fork deleted")


if __name__ == "__main__":
    main()
