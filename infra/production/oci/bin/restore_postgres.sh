#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: restore_postgres.sh --input /opt/pokeleximon/backups/postgres_YYYYMMDDTHHMMSSZ.sql.gz [--root /opt/pokeleximon] --yes
EOF
}

ROOT="/opt/pokeleximon"
INPUT_PATH=""
CONFIRMED="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUT_PATH="$2"
      shift 2
      ;;
    --root)
      ROOT="$2"
      shift 2
      ;;
    --yes)
      CONFIRMED="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${INPUT_PATH}" || "${CONFIRMED}" != "true" ]]; then
  usage >&2
  exit 1
fi

if [[ ! -f "${INPUT_PATH}" ]]; then
  printf 'Backup file not found: %s\n' "${INPUT_PATH}" >&2
  exit 1
fi

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

COMPOSE=(docker compose --env-file "${DEPLOY_ENV}" -f "${COMPOSE_FILE}")

"${COMPOSE[@]}" exec -T db sh -lc \
  'PGPASSWORD="$POSTGRES_PASSWORD" dropdb --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" && PGPASSWORD="$POSTGRES_PASSWORD" createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'

gzip -dc "${INPUT_PATH}" | "${COMPOSE[@]}" exec -T db sh -lc \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

printf 'Restored backup: %s\n' "${INPUT_PATH}"
