#!/usr/bin/env bash
# Start a local TimescaleDB in Docker on port 5433 and apply the schema. Safe to run twice.
# Windows: run with Git Bash ("C:\Program Files\Git\bin\bash.exe" scripts/dev_db.sh), not WSL's bash.
# psql runs inside the container, so no host psql is needed; the schema goes in on stdin,
# which also avoids Git Bash rewriting /paths.
set -euo pipefail
cd "$(dirname "$0")/.."

NAME=tempo-db
PORT=5433
PASS=tempo
IMAGE=timescale/timescaledb-ha:pg17

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon not reachable: start Docker Desktop first" >&2
  exit 1
fi

if ! docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker run -d --name "$NAME" -p "$PORT:5432" -e POSTGRES_PASSWORD="$PASS" "$IMAGE" >/dev/null
  echo "started $NAME"
elif ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  docker start "$NAME" >/dev/null
  echo "restarted $NAME"
fi

# The ha image restarts postgres once after initdb, so wait for a real query, not just pg_isready.
for _ in $(seq 1 60); do
  if docker exec "$NAME" psql -U postgres -d postgres -tAc 'select 1' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ -z "${ready:-}" ]; then
  echo "$NAME did not become ready in 60 s" >&2
  exit 1
fi

docker exec -i "$NAME" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q < tempo/db/schema.sql
echo "schema applied: postgres://postgres:$PASS@localhost:$PORT/postgres"
