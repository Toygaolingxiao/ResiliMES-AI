#!/usr/bin/env bash
# Idempotent reload of fab-mes and the three Zetaris datasources.
# From Windows: wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh [seed.sql]
# Secrets are never printed. See docs/ZETARIS.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="${1:-$ROOT/data/sql/seed.sql}"
KERNEL="$ROOT/data/sql/kernel.sql"
CONF_DIR="${HOME}/.config/fab-mes"
ENV_FILE="$CONF_DIR/env"

if [[ ! -f "$SEED" ]]; then
  echo "Seed SQL not found: $SEED" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to start fab-mes." >&2
  exit 1
fi

mkdir -p "$CONF_DIR"
chmod 700 "$CONF_DIR"

docker network inspect fab-net >/dev/null 2>&1 || docker network create fab-net

if docker ps -a --format '{{.Names}}' | grep -qx 'fab-mes'; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "fab-mes already exists but ${ENV_FILE} is missing. Refusing to invent a new password." >&2
    exit 1
  fi
  docker start fab-mes >/dev/null
  docker network connect fab-net fab-mes >/dev/null 2>&1 || true
else
  if [[ ! -f "$ENV_FILE" ]]; then
    umask 077
    password="$(openssl rand -hex 24)"
    printf 'POSTGRES_USER=fab\nPOSTGRES_PASSWORD=%s\n' "$password" >"$ENV_FILE"
    chmod 0600 "$ENV_FILE"
    unset password
  fi
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
  docker run -d --name fab-mes --network fab-net \
    -e POSTGRES_USER="${POSTGRES_USER}" \
    -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    -p 127.0.0.1:5433:5432 \
    postgres:16-alpine >/dev/null
fi

if docker ps -a --format '{{.Names}}' | grep -qx 'zetaris-driver-1'; then
  docker network connect fab-net zetaris-driver-1 >/dev/null 2>&1 || true
  echo "Attached zetaris-driver-1 to fab-net."
else
  echo "zetaris-driver-1 is not on this machine; Postgres load will still run."
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

echo "Waiting for Postgres on 127.0.0.1:5433."
ready=0
for _ in $(seq 1 40); do
  if docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" fab-mes \
    pg_isready -U "${POSTGRES_USER}" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Postgres did not become ready." >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/fab-mes.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

PYTHONPATH="$ROOT" python3 - "$SEED" "$KERNEL" "$WORK" <<'PY'
import sys
from pathlib import Path

from resilimes.data.zetaris_layout import write_split

seed, kernel, directory = (Path(arg) for arg in sys.argv[1:])
paths = [seed]
if kernel.is_file():
    paths.append(kernel)
written = write_split(paths, directory)
print("split " + " ".join(sorted(written)))
PY

for database in fab_mes fab_cmms fab_erp; do
  exists="$(docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" fab-mes \
    psql -U "${POSTGRES_USER}" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${database}'" || true)"
  if [[ "${exists}" != "1" ]]; then
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" fab-mes \
      psql -U "${POSTGRES_USER}" -d postgres -c "CREATE DATABASE ${database}" >/dev/null
  fi
  docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" fab-mes \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${database}" \
    <"${WORK}/${database}.sql" >/dev/null
  echo "Loaded ${database}."
done

echo "Registering Zetaris datasources."
PYTHONPATH="$ROOT" python3 -m resilimes.data.zetaris_admin
echo "Reload finished."
