#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[deploy] %s\n' "$1"
}

usage() {
  cat <<'EOF'
Usage: deploy_remote.sh --release-archive /tmp/pokeleximon.tgz --release-id <id> [--root /opt/pokeleximon]
EOF
}

ROOT="/opt/pokeleximon"
RELEASE_ARCHIVE=""
RELEASE_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-archive)
      RELEASE_ARCHIVE="$2"
      shift 2
      ;;
    --release-id)
      RELEASE_ID="$2"
      shift 2
      ;;
    --root)
      ROOT="$2"
      shift 2
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

if [[ -z "${RELEASE_ARCHIVE}" || -z "${RELEASE_ID}" ]]; then
  usage >&2
  exit 1
fi

if [[ ! -f "${RELEASE_ARCHIVE}" ]]; then
  printf 'Release archive not found: %s\n' "${RELEASE_ARCHIVE}" >&2
  exit 1
fi

APP_DIR="${ROOT}/app"
DEPLOY_ENV="${APP_DIR}/deploy.env"
WEB_ENV="${APP_DIR}/web.env"
SECRETS_DIR="${ROOT}/secrets"
API_ENV="${SECRETS_DIR}/api.env"
RELEASES_DIR="${APP_DIR}/releases"
RELEASE_DIR="${RELEASES_DIR}/${RELEASE_ID}"
CURRENT_LINK="${APP_DIR}/current"

if [[ ! -f "${DEPLOY_ENV}" ]]; then
  printf 'Missing deploy env: %s\n' "${DEPLOY_ENV}" >&2
  exit 1
fi

if [[ ! -f "${API_ENV}" ]]; then
  printf 'Missing API env: %s\n' "${API_ENV}" >&2
  exit 1
fi

if [[ -e "${RELEASE_DIR}" ]]; then
  printf 'Release already exists: %s\n' "${RELEASE_DIR}" >&2
  exit 1
fi

install -d -m 0755 "${RELEASES_DIR}" "${ROOT}/bin"

log "Extracting release ${RELEASE_ID}"
mkdir -p "${RELEASE_DIR}"
tar -xzf "${RELEASE_ARCHIVE}" -C "${RELEASE_DIR}"

for script_name in backup_postgres.sh create_secrets.sh preflight.sh restore_postgres.sh; do
  install -m 0755 \
    "${RELEASE_DIR}/infra/production/oci/bin/${script_name}" \
    "${ROOT}/bin/${script_name}"
done

set -a
. "${DEPLOY_ENV}"
if [[ -f "${WEB_ENV}" ]]; then
  . "${WEB_ENV}"
fi
set +a

export POKELEXIMON_ROOT="${POKELEXIMON_ROOT:-${ROOT}}"
export POKELEXIMON_APP_ROOT="${POKELEXIMON_APP_ROOT:-${CURRENT_LINK}}"
export POKELEXIMON_SECRETS_DIR="${POKELEXIMON_SECRETS_DIR:-${SECRETS_DIR}}"
export POKELEXIMON_DATA_DIR="${POKELEXIMON_DATA_DIR:-${ROOT}/data}"
export POKELEXIMON_ARTIFACTS_DIR="${POKELEXIMON_ARTIFACTS_DIR:-${ROOT}/data/artifacts}"
export POKELEXIMON_BACKUPS_DIR="${POKELEXIMON_BACKUPS_DIR:-${ROOT}/backups}"
export WEB_SENTRY_RELEASE="${WEB_SENTRY_RELEASE:-${RELEASE_ID}}"

ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

COMPOSE_FILE="${CURRENT_LINK}/infra/production/oci/docker-compose.prod.yml"
COMPOSE=(docker compose --env-file "${DEPLOY_ENV}" -f "${COMPOSE_FILE}")

log "Starting data services"
"${COMPOSE[@]}" up -d db redis

log "Waiting for Postgres"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! "${COMPOSE[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
  printf 'Postgres did not become ready in time\n' >&2
  exit 1
fi

log "Running migrations"
"${COMPOSE[@]}" run --rm api alembic -c alembic.ini upgrade head

log "Building and starting application services"
"${COMPOSE[@]}" up -d --build

log "Waiting for API health"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! "${COMPOSE[@]}" exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)' >/dev/null 2>&1; then
  printf 'API health check failed after deploy\n' >&2
  exit 1
fi

if command -v curl >/dev/null 2>&1; then
  log "Verifying same-origin proxy"
  if curl -fsS -H "Host: ${SITE_HOST:-localhost}" http://127.0.0.1/health >/dev/null 2>&1; then
    :
  elif curl -kfsS --resolve "${SITE_HOST:-localhost}:443:127.0.0.1" "https://${SITE_HOST:-localhost}/health" >/dev/null 2>&1; then
    :
  else
    printf 'Proxy health check failed\n' >&2
    exit 1
  fi
fi

rm -f "${RELEASE_ARCHIVE}"

log "Deploy complete: ${RELEASE_ID}"
