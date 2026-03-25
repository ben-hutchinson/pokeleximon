#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/opt/pokeleximon}"
APP_DIR="${ROOT}/app"
DEPLOY_ENV="${APP_DIR}/deploy.env"
COMPOSE_FILE="${APP_DIR}/current/infra/production/aws-ec2/docker-compose.prod.yml"

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
export AWS_REGION="${AWS_REGION:-eu-west-2}"

mkdir -p "${POKELEXIMON_BACKUPS_DIR}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_PATH="${POKELEXIMON_BACKUPS_DIR}/postgres_${STAMP}.sql.gz"

COMPOSE=(docker compose --env-file "${DEPLOY_ENV}" -f "${COMPOSE_FILE}")

"${COMPOSE[@]}" exec -T db sh -lc \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' \
  | gzip -c > "${OUTPUT_PATH}"

if [[ "${BACKUP_S3_ENABLED:-false}" == "true" ]]; then
  if ! command -v aws >/dev/null 2>&1; then
    printf 'aws CLI is required when BACKUP_S3_ENABLED=true\n' >&2
    exit 1
  fi
  if [[ -z "${BACKUP_S3_URI:-}" ]]; then
    printf 'BACKUP_S3_URI must be set when BACKUP_S3_ENABLED=true\n' >&2
    exit 1
  fi

  aws s3 cp "${OUTPUT_PATH}" "${BACKUP_S3_URI%/}/$(basename "${OUTPUT_PATH}")"
fi

find "${POKELEXIMON_BACKUPS_DIR}" -type f -name 'postgres_*.sql.gz' -mtime +14 -delete

printf 'Wrote backup: %s\n' "${OUTPUT_PATH}"
