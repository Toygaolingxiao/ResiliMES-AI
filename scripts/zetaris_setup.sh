#!/usr/bin/env bash
# ResiliMES-AI -> Zetaris: load the fab source databases and register them in a local Zetaris.
#
# From Windows: wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh [seed.sql ...]
# Inside WSL:   bash scripts/zetaris_setup.sh [seed.sql ...]
#
# With no arguments it loads data/sql/seed.sql and data/sql/smt2020_seed.sql
# (plus data/sql/kernel.sql). Idempotent: every run rebuilds schema resilimes in
# fab_mes, fab_cmms and fab_erp from exactly the seeds given, re-registers the
# Zetaris datasources resilimes / fab_cmms / fab_erp, and runs one SELECT per
# loaded table plus the federated join through the Zetaris REST API.
#
# Sources (one Postgres container "fab-mes", 127.0.0.1:5433, docker network fab-net):
#   db fab_mes   schema resilimes -> datasource resilimes  (MES, incl. SMT2020 smt_*)
#   db fab_cmms  schema resilimes -> datasource fab_cmms   (maintenance_logs, pm_calendar, smt_pmcal/attach/downcal)
#   db fab_erp   schema resilimes -> datasource fab_erp    (bom, materials, orders, smt_order)
#
# Secrets: the Zetaris admin login comes from $ZETARIS_HOME/.env (ZETARIS_ADMIN_EMAIL,
# ZETARIS_ADMIN_PASSWORD), else ZETARIS_USER / ZETARIS_PASSWORD in ~/.config/fab-mes/env.
# The Postgres login is FAB_PG_USER / FAB_PG_PASSWORD in ~/.config/fab-mes/env (older
# files with POSTGRES_USER / POSTGRES_PASSWORD still work). The file is created once
# (0600) only when neither it nor the container exists. Nothing secret is printed.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/.." && pwd)"
ZETARIS_HOME="${ZETARIS_HOME:-$HOME/zetaris-platform}"
DRIVER_CONTAINER="${DRIVER_CONTAINER:-zetaris-driver-1}"
FAB_CONTAINER=fab-mes
FAB_NET=fab-net
FAB_PORT="${FAB_PORT:-5433}"
KERNEL="$ROOT/data/sql/kernel.sql"
CFG="$HOME/.config/fab-mes/env"
export ZETARIS_HOME

log() { printf '[zetaris-setup] %s\n' "$*"; }

# --- seeds ----------------------------------------------------------------------------------
SEEDS=("$@")
if [[ ${#SEEDS[@]} -eq 0 ]]; then
  SEEDS=("$ROOT/data/sql/seed.sql")
  if [[ -f "$ROOT/data/sql/smt2020_seed.sql" ]]; then
    SEEDS+=("$ROOT/data/sql/smt2020_seed.sql")
  fi
fi
for index in "${!SEEDS[@]}"; do
  seed="${SEEDS[$index]}"
  if [[ ! -f "$seed" && -f "$ROOT/$seed" ]]; then
    seed="$ROOT/$seed"
  fi
  if [[ ! -f "$seed" ]]; then
    echo "Seed SQL not found: $seed" >&2
    exit 1
  fi
  SEEDS[$index]="$(cd "$(dirname "$seed")" && pwd)/$(basename "$seed")"
done

command -v docker >/dev/null 2>&1 || { echo "docker is required to start fab-mes." >&2; exit 1; }

# --- credentials ----------------------------------------------------------------------------
# Read KEY=value from the env file without sourcing it (last one wins, CR and quotes stripped).
env_value() {
  local key="$1"
  [[ -f "$CFG" ]] || return 0
  sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?${key}=//p" "$CFG" | tail -1 | tr -d '\r' |
    sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

container_exists=0
if docker inspect "$FAB_CONTAINER" >/dev/null 2>&1; then
  container_exists=1
fi

if [[ ! -f "$CFG" ]]; then
  if [[ "$container_exists" -eq 1 ]]; then
    echo "$FAB_CONTAINER exists but $CFG is missing. Refusing to invent a new password." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$CFG")"
  chmod 700 "$(dirname "$CFG")"
  (
    umask 077
    printf 'FAB_PG_USER=fab\nFAB_PG_PASSWORD=%s\n' \
      "$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 24)" >"$CFG"
  )
  chmod 600 "$CFG"
  log "wrote $CFG (FAB_PG_USER, FAB_PG_PASSWORD; not printed)"
fi

FAB_PG_USER="$(env_value FAB_PG_USER)"
FAB_PG_PASSWORD="$(env_value FAB_PG_PASSWORD)"
if [[ -z "$FAB_PG_USER" ]]; then FAB_PG_USER="$(env_value POSTGRES_USER)"; fi
if [[ -z "$FAB_PG_PASSWORD" ]]; then FAB_PG_PASSWORD="$(env_value POSTGRES_PASSWORD)"; fi
FAB_PG_USER="${FAB_PG_USER:-fab}"
if [[ -z "$FAB_PG_PASSWORD" ]]; then
  echo "$CFG has neither FAB_PG_PASSWORD nor POSTGRES_PASSWORD." >&2
  exit 1
fi

# --- container + network --------------------------------------------------------------------
docker network inspect "$FAB_NET" >/dev/null 2>&1 || docker network create "$FAB_NET" >/dev/null
if [[ "$container_exists" -eq 0 ]]; then
  log "starting $FAB_CONTAINER on 127.0.0.1:$FAB_PORT"
  docker run -d --name "$FAB_CONTAINER" --restart unless-stopped --network "$FAB_NET" \
    -p "127.0.0.1:$FAB_PORT:5432" -e POSTGRES_USER="$FAB_PG_USER" \
    -e POSTGRES_PASSWORD="$FAB_PG_PASSWORD" -e POSTGRES_DB=fab_mes \
    -v fab-mes-data:/var/lib/postgresql/data postgres:16-alpine >/dev/null
else
  docker start "$FAB_CONTAINER" >/dev/null
  docker network connect "$FAB_NET" "$FAB_CONTAINER" >/dev/null 2>&1 || true
fi
# The driver opens the JDBC connections. Re-attach after every `docker compose up`.
if docker inspect "$DRIVER_CONTAINER" >/dev/null 2>&1; then
  if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$DRIVER_CONTAINER" | grep -q "\"$FAB_NET\""; then
    docker network connect "$FAB_NET" "$DRIVER_CONTAINER"
  fi
  log "$DRIVER_CONTAINER is on $FAB_NET"
else
  log "$DRIVER_CONTAINER is not on this machine; Postgres load will still run"
fi

log "waiting for Postgres on 127.0.0.1:$FAB_PORT"
ready=0
for _ in $(seq 60); do
  if docker exec "$FAB_CONTAINER" pg_isready -h 127.0.0.1 -U "$FAB_PG_USER" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Postgres did not become ready." >&2
  exit 1
fi

# --- split + load ---------------------------------------------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/fab-mes.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

PYTHONPATH="$ROOT" python3 - "$WORK" "$KERNEL" "${SEEDS[@]}" <<'PY'
import sys
from pathlib import Path

from resilimes.data.zetaris_layout import tables_in, write_split

directory, kernel, *seeds = (Path(arg) for arg in sys.argv[1:])
paths = list(seeds)
if kernel.is_file():
    paths.append(kernel)
written = write_split(paths, directory)
tables = tables_in(paths)
(directory / "tables.txt").write_text(",".join(tables), encoding="utf-8")
print("[zetaris-setup] seeds " + " ".join(path.name for path in paths))
print("[zetaris-setup] split " + " ".join(sorted(written)) + f" tables={len(tables)}")
PY

psql_fab() {
  docker exec -i -e PGOPTIONS="-c client_min_messages=warning" "$FAB_CONTAINER" \
    psql -U "$FAB_PG_USER" -v ON_ERROR_STOP=1 -q "$@"
}
for database in fab_mes fab_cmms fab_erp; do
  exists="$(psql_fab -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${database}'" || true)"
  if [[ "${exists}" != "1" ]]; then
    psql_fab -d postgres -c "CREATE DATABASE ${database}" >/dev/null
  fi
  psql_fab -d "$database" <"${WORK}/${database}.sql" >/dev/null
  log "$database: $(psql_fab -d "$database" -At -c "select count(*) from pg_tables where schemaname='resilimes'") tables in resilimes"
done

# --- register + query through Zetaris -------------------------------------------------------
log "registering Zetaris datasources"
RESILIMES_LOADED_TABLES="$(cat "${WORK}/tables.txt")" \
  PYTHONPATH="$ROOT" python3 -m resilimes.data.zetaris_admin
log "reload finished"
