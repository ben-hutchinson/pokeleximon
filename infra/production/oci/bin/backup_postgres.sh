#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/opt/pokeleximon}"
APP_DIR="${ROOT}/app"
DEPLOY_ENV="${APP_DIR}/deploy.env"
COMPOSE_FILE="${APP_DIR}/current/infra/production/oci/docker-compose.prod.yml"

if [[ ! -f "${DEPLOY_ENV}" ]]; then
  printf 'Missing deploy env: %s\n' "${DEPLOY_ENV}" >&2
  exit 1
fi

set -a
. "${DEPLOY_ENV}"
set +a

export POKELEXIMON_APP_ROOT="${POKELEXIMON_APP_ROOT:-${ROOT}/app/current}"
export POKELEXIMON_SECRETS_DIR="${POKELEXIMON_SECRETS_DIR:-${ROOT}/secrets}"
export POKELEXIMON_DATA_DIR="${POKELEXIMON_DATA_DIR:-${ROOT}/data}"
export POKELEXIMON_ARTIFACTS_DIR="${POKELEXIMON_ARTIFACTS_DIR:-${ROOT}/data/artifacts}"
export POKELEXIMON_BACKUPS_DIR="${POKELEXIMON_BACKUPS_DIR:-${ROOT}/backups}"

mkdir -p "${POKELEXIMON_BACKUPS_DIR}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_PATH="${POKELEXIMON_BACKUPS_DIR}/postgres_${STAMP}.sql.gz"

COMPOSE=(docker compose --env-file "${DEPLOY_ENV}" -f "${COMPOSE_FILE}")

"${COMPOSE[@]}" exec -T db sh -lc \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' \
  | gzip -c > "${OUTPUT_PATH}"

find "${POKELEXIMON_BACKUPS_DIR}" -type f -name 'postgres_*.sql.gz' -mtime +14 -delete

printf 'Wrote backup: %s\n' "${OUTPUT_PATH}"
