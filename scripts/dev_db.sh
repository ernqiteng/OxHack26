#!/usr/bin/env bash
# Start a local TimescaleDB in Docker on port 5433 and apply the schema. Safe to run twice.
set -euo pipefail
cd "$(dirname "$0")/.."

NAME=tempo-db
PORT=5433
PASS=tempo

if ! docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker run -d --name "$NAME" -p "$PORT:5432" -e POSTGRES_PASSWORD="$PASS" timescale/timescaledb-ha:pg17 >/dev/null
  echo "started $NAME"
elif ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  docker start "$NAME" >/dev/null
  echo "restarted $NAME"
fi

until docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

export PGPASSWORD="$PASS"
psql -h localhost -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f tempo/db/schema.sql
echo "schema applied: postgres://postgres:$PASS@localhost:$PORT/postgres"
