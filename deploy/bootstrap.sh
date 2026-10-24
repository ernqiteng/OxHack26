#!/usr/bin/env bash
# Turn a fresh Ubuntu 24.04 box into a Tempo box. The code must already be in /opt/tempo (the repo is
# private, so scripts/build_worker_image.py copies it over with rsync instead of git clone).
#
#   ROLE=worker TEMPO_WORKER_TOKEN=... bash /opt/tempo/deploy/bootstrap.sh    # replay worker on :8000
#   ROLE=backend bash /opt/tempo/deploy/bootstrap.sh                          # dashboard :8501 + poller
#
# Safe to run twice. Works in a plain Docker container too (systemd and ufw steps are skipped there).
set -euo pipefail

ROLE="${ROLE:-worker}"
APP=/opt/tempo
[ -f "$APP/pyproject.toml" ] || { echo "no code in $APP; copy the repo there first"; exit 1; }
HAVE_SYSTEMD=0; [ -d /run/systemd/system ] && HAVE_SYSTEMD=1

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip rsync curl ca-certificates

# 1 GB plans: pip builds and lightgbm imports want headroom.
if [ "$HAVE_SYSTEMD" = 1 ] && ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

id -u tempo >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash tempo
mkdir -p /var/log/tempo /etc/tempo
chown -R tempo:tempo "$APP" /var/log/tempo

sudo -u tempo bash -c "cd $APP && python3 -m venv .venv && .venv/bin/pip install -q -U pip && .venv/bin/pip install -q -e ."
sudo -u tempo "$APP/.venv/bin/python" -c "import tempo.worker.main, tempo.audit.shifts; print('tempo imports ok')"

if [ "$ROLE" = worker ]; then
  if [ -n "${TEMPO_WORKER_TOKEN:-}" ]; then
    (umask 077; printf 'TEMPO_WORKER_TOKEN=%s\n' "$TEMPO_WORKER_TOKEN" > /etc/tempo/worker.env)
    chown root:tempo /etc/tempo/worker.env; chmod 640 /etc/tempo/worker.env
  else
    echo "WARNING: no TEMPO_WORKER_TOKEN; /replay will accept anyone"
  fi
fi

if [ "$HAVE_SYSTEMD" = 1 ]; then
  install -m 644 "$APP"/deploy/systemd/*.service /etc/systemd/system/
  systemctl daemon-reload
  if [ "$ROLE" = worker ]; then
    systemctl enable --now tempo-worker
    systemctl restart tempo-worker
  fi
  if command -v ufw >/dev/null; then
    ufw allow OpenSSH >/dev/null
    if [ "$ROLE" = worker ]; then ufw allow 8000/tcp >/dev/null; else ufw allow 8501/tcp >/dev/null; fi
    ufw --force enable >/dev/null
  fi
fi
# Flush to disk: a block-level snapshot taken seconds after this can otherwise capture zero-byte unit
# and env files (ext4 delayed allocation), which left the first worker image with a masked service.
sync
echo "bootstrap done (role=$ROLE, systemd=$HAVE_SYSTEMD)"
