#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 Vultr instance as a Tempo box (backend or worker).
#   ssh root@<ip> 'bash -s' < deploy/bootstrap.sh
#   then: scp .env root@<ip>:/opt/tempo/.env   (backend only; workers get DSNs per request)
#   then: ssh root@<ip> 'systemctl enable --now tempo-dashboard tempo-poller'   (backend)
#         ssh root@<ip> 'systemctl enable --now tempo-worker'                   (worker)
set -euo pipefail

REPO_URL="${TEMPO_REPO_URL:-https://github.com/REPLACE_ME/OxHack26.git}"
BRANCH="${TEMPO_BRANCH:-main}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip git postgresql-client ufw

id -u tempo >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash tempo
mkdir -p /opt/tempo /var/log/tempo
chown tempo:tempo /var/log/tempo

if [ ! -d /opt/tempo/.git ]; then
  git clone --branch "$BRANCH" "$REPO_URL" /opt/tempo
else
  git -C /opt/tempo pull --ff-only
fi
chown -R tempo:tempo /opt/tempo

sudo -u tempo bash -c 'cd /opt/tempo && python3 -m venv .venv && .venv/bin/pip install -q -U pip && .venv/bin/pip install -q -e .'

cp /opt/tempo/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload

ufw allow OpenSSH
ufw allow 8501/tcp   # dashboard
ufw allow 8000/tcp   # worker API
ufw --force enable

echo "bootstrap done. Next: copy .env to /opt/tempo/.env (backend) and enable the units you need."
