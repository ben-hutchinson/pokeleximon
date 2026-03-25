#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: preflight.sh [--root /opt/pokeleximon] [--check-build]

Checks production deployment files, local secret hygiene, and optional frontend
bundle safety before deploying.
EOF
}

ROOT="/opt/pokeleximon"
CHECK_BUILD="false"
FAILED="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$2"
      shift 2
      ;;
    --check-build)
      CHECK_BUILD="true"
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

APP_DIR="${ROOT}/app"
DEPLOY_ENV="${APP_DIR}/deploy.env"
WEB_ENV="${APP_DIR}/web.env"
SECRETS_DIR="${ROOT}/secrets"
API_ENV="${SECRETS_DIR}/api.env"
PROXY_ENV="${SECRETS_DIR}/proxy.env"
MONITORING_ENV="${SECRETS_DIR}/monitoring.env"
ACCESS_FILE="${SECRETS_DIR}/admin_access.txt"
CURRENT_LINK="${APP_DIR}/current"

pass() {
  printf '[ok] %s\n' "$1"
}

fail() {
  printf '[fail] %s\n' "$1" >&2
  FAILED="true"
}

check_exists() {
  local path="$1"
  if [[ -e "${path}" ]]; then
    pass "exists: ${path}"
  else
    fail "missing: ${path}"
  fi
}

check_no_pattern() {
  local path="$1"
  local pattern="$2"
  local label="$3"
  if [[ ! -f "${path}" ]]; then
    fail "missing file for pattern check: ${path}"
    return
  fi
  if grep -qE "${pattern}" "${path}"; then
    fail "${label}: ${path}"
  else
    pass "${label}: ${path}"
  fi
}

check_mode() {
  local path="$1"
  local expected="$2"
  if [[ ! -e "${path}" ]]; then
    fail "missing for permission check: ${path}"
    return
  fi

  local actual
  actual="$(stat -c '%a' "${path}" 2>/dev/null || stat -f '%Lp' "${path}" 2>/dev/null || true)"
  if [[ "${actual}" == "${expected}" ]]; then
    pass "permissions ${expected}: ${path}"
  else
    fail "permissions ${actual:-unknown} on ${path}, expected ${expected}"
  fi
}

check_exists "${DEPLOY_ENV}"
check_exists "${API_ENV}"
check_exists "${PROXY_ENV}"
check_exists "${MONITORING_ENV}"
check_exists "${ACCESS_FILE}"
check_exists "${SECRETS_DIR}"

if [[ -e "${SECRETS_DIR}" ]]; then
  check_mode "${SECRETS_DIR}" "700"
fi
if [[ -f "${API_ENV}" ]]; then
  check_mode "${API_ENV}" "600"
  check_no_pattern "${API_ENV}" 'CHANGE_ME_ON_SERVER_ONLY' 'no placeholder secrets remain'
  check_no_pattern "${API_ENV}" '^VITE_ADMIN_API_TOKEN=' 'frontend admin token absent from api env'
fi
if [[ -f "${PROXY_ENV}" ]]; then
  check_mode "${PROXY_ENV}" "600"
  check_no_pattern "${PROXY_ENV}" 'CHANGE_ME_HASHED_ON_SERVER_ONLY' 'proxy password hash generated'
fi
if [[ -f "${MONITORING_ENV}" ]]; then
  check_mode "${MONITORING_ENV}" "600"
  check_no_pattern "${MONITORING_ENV}" 'CHANGE_ME_ON_SERVER_ONLY' 'grafana admin password generated'
fi
if [[ -f "${ACCESS_FILE}" ]]; then
  check_mode "${ACCESS_FILE}" "600"
fi
if [[ -f "${DEPLOY_ENV}" ]]; then
  check_no_pattern "${DEPLOY_ENV}" '^VITE_ADMIN_API_TOKEN=' 'frontend admin token absent from deploy env'
  if grep -qE '^BACKUP_S3_ENABLED=true$' "${DEPLOY_ENV}"; then
    if [[ -n "$(grep -E '^BACKUP_S3_URI=s3://.+' "${DEPLOY_ENV}" || true)" ]]; then
      pass "backup S3 target configured"
    else
      fail "BACKUP_S3_ENABLED=true but BACKUP_S3_URI is missing or invalid"
    fi
    if command -v aws >/dev/null 2>&1; then
      pass "aws CLI available for S3 backups"
    else
      fail "aws CLI not found but BACKUP_S3_ENABLED=true"
    fi
  fi
fi
if [[ -f "${WEB_ENV}" ]]; then
  check_no_pattern "${WEB_ENV}" '^VITE_ADMIN_API_TOKEN=' 'frontend admin token absent from web env'
fi
if [[ -L "${CURRENT_LINK}" ]]; then
  pass "current symlink present: ${CURRENT_LINK}"
fi

if [[ "${CHECK_BUILD}" == "true" ]]; then
  DIST_DIR="${CURRENT_LINK}/apps/web/dist"
  if [[ -d "${DIST_DIR}" ]]; then
    if grep -R -nE 'VITE_ADMIN_API_TOKEN|ci-admin-token|change-me-admin-token' "${DIST_DIR}" >/dev/null 2>&1; then
      fail "admin token marker found in frontend build: ${DIST_DIR}"
    else
      pass "frontend build contains no admin token markers"
    fi
  else
    fail "frontend build directory not found: ${DIST_DIR}"
  fi
fi

if [[ "${FAILED}" == "true" ]]; then
  exit 1
fi
