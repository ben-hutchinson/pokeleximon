#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: create_secrets.sh [--root /opt/pokeleximon] [--force]

Creates server-local secret files from the committed templates, generates fresh
admin/API/proxy secrets in place, and locks file permissions. Secret values are
never printed to stdout.
EOF
}

ROOT="/opt/pokeleximon"
FORCE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$2"
      shift 2
      ;;
    --force)
      FORCE="true"
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_PATH="${SCRIPT_DIR}/../env/api.env.template"
PROXY_TEMPLATE_PATH="${SCRIPT_DIR}/../env/proxy.env.template"
MONITORING_TEMPLATE_PATH="${SCRIPT_DIR}/../env/monitoring.env.template"
SECRETS_DIR="${ROOT}/secrets"
TARGET_PATH="${SECRETS_DIR}/api.env"
PROXY_TARGET_PATH="${SECRETS_DIR}/proxy.env"
MONITORING_TARGET_PATH="${SECRETS_DIR}/monitoring.env"
ACCESS_TARGET_PATH="${SECRETS_DIR}/admin_access.txt"

if [[ ! -f "${TEMPLATE_PATH}" || ! -f "${PROXY_TEMPLATE_PATH}" || ! -f "${MONITORING_TEMPLATE_PATH}" ]]; then
  printf 'Template not found: %s\n' "${TEMPLATE_PATH}" >&2
  exit 1
fi

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr -d '\n' | tr '/+' '_-' | cut -c1-64
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
  else
    head -c 48 /dev/urandom | base64 | tr -d '\n' | tr '/+' '_-' | cut -c1-64
  fi
}

hash_password() {
  local password="$1"
  if command -v caddy >/dev/null 2>&1; then
    caddy hash-password --plaintext "${password}"
  elif command -v docker >/dev/null 2>&1; then
    docker run --rm caddy:2.8-alpine caddy hash-password --plaintext "${password}"
  else
    printf 'Need either caddy or docker available to generate the proxy password hash.\n' >&2
    exit 1
  fi
}

if [[ -f "${TARGET_PATH}" && "${FORCE}" != "true" ]]; then
  printf 'Refusing to overwrite existing secret file: %s\n' "${TARGET_PATH}" >&2
  printf 'Re-run with --force if you intend to rotate all generated secrets.\n' >&2
  exit 1
fi

if [[ -f "${PROXY_TARGET_PATH}" && "${FORCE}" != "true" ]]; then
  printf 'Refusing to overwrite existing secret file: %s\n' "${PROXY_TARGET_PATH}" >&2
  printf 'Re-run with --force if you intend to rotate all generated secrets.\n' >&2
  exit 1
fi

if [[ -f "${MONITORING_TARGET_PATH}" && "${FORCE}" != "true" ]]; then
  printf 'Refusing to overwrite existing secret file: %s\n' "${MONITORING_TARGET_PATH}" >&2
  printf 'Re-run with --force if you intend to rotate all generated secrets.\n' >&2
  exit 1
fi

install -d -m 0700 "${SECRETS_DIR}"

ADMIN_TOKEN="$(generate_secret)"
DB_PASSWORD="$(generate_secret)"
PROXY_USER="admin"
PROXY_PASSWORD="$(generate_secret)"
PROXY_PASSWORD_HASH="$(hash_password "${PROXY_PASSWORD}")"
PROXY_PASSWORD_HASH_ESCAPED="${PROXY_PASSWORD_HASH//$/$$}"
GRAFANA_USER="admin"
GRAFANA_PASSWORD="$(generate_secret)"

TMP_FILE="$(mktemp "${SECRETS_DIR}/api.env.XXXXXX")"
PROXY_TMP_FILE="$(mktemp "${SECRETS_DIR}/proxy.env.XXXXXX")"
MONITORING_TMP_FILE="$(mktemp "${SECRETS_DIR}/monitoring.env.XXXXXX")"
ACCESS_TMP_FILE="$(mktemp "${SECRETS_DIR}/admin_access.XXXXXX")"
trap 'rm -f "${TMP_FILE}" "${PROXY_TMP_FILE}" "${MONITORING_TMP_FILE}" "${ACCESS_TMP_FILE}"' EXIT

cp "${TEMPLATE_PATH}" "${TMP_FILE}"
cp "${PROXY_TEMPLATE_PATH}" "${PROXY_TMP_FILE}"
cp "${MONITORING_TEMPLATE_PATH}" "${MONITORING_TMP_FILE}"

python3 - "${TMP_FILE}" "${ADMIN_TOKEN}" "${DB_PASSWORD}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
admin_token = sys.argv[2]
db_password = sys.argv[3]

text = path.read_text()
text = text.replace("ADMIN_AUTH_TOKEN=CHANGE_ME_ON_SERVER_ONLY", f"ADMIN_AUTH_TOKEN={admin_token}")
text = text.replace("POSTGRES_PASSWORD=CHANGE_ME_ON_SERVER_ONLY", f"POSTGRES_PASSWORD={db_password}")
text = text.replace(
    "DATABASE_URL=postgresql+psycopg://pokeleximon:CHANGE_ME_ON_SERVER_ONLY@db:5432/pokeleximon",
    f"DATABASE_URL=postgresql+psycopg://pokeleximon:{db_password}@db:5432/pokeleximon",
)
path.write_text(text)
PY

python3 - "${PROXY_TMP_FILE}" "${PROXY_USER}" "${PROXY_PASSWORD_HASH_ESCAPED}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
username = sys.argv[2]
password_hash = sys.argv[3]

text = path.read_text()
text = text.replace("PROXY_BASIC_AUTH_USER=admin", f"PROXY_BASIC_AUTH_USER={username}")
text = text.replace("PROXY_BASIC_AUTH_PASSWORD_HASH=CHANGE_ME_HASHED_ON_SERVER_ONLY", f"PROXY_BASIC_AUTH_PASSWORD_HASH={password_hash}")
path.write_text(text)
PY

python3 - "${MONITORING_TMP_FILE}" "${GRAFANA_USER}" "${GRAFANA_PASSWORD}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
username = sys.argv[2]
password = sys.argv[3]

text = path.read_text()
text = text.replace("GF_SECURITY_ADMIN_USER=admin", f"GF_SECURITY_ADMIN_USER={username}")
text = text.replace("GF_SECURITY_ADMIN_PASSWORD=CHANGE_ME_ON_SERVER_ONLY", f"GF_SECURITY_ADMIN_PASSWORD={password}")
path.write_text(text)
PY

cat > "${ACCESS_TMP_FILE}" <<EOF
ADMIN_AUTH_TOKEN=${ADMIN_TOKEN}
PROXY_BASIC_AUTH_USER=${PROXY_USER}
PROXY_BASIC_AUTH_PASSWORD=${PROXY_PASSWORD}
GRAFANA_ADMIN_USER=${GRAFANA_USER}
GRAFANA_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
EOF

install -m 0600 "${TMP_FILE}" "${TARGET_PATH}"
install -m 0600 "${PROXY_TMP_FILE}" "${PROXY_TARGET_PATH}"
install -m 0600 "${MONITORING_TMP_FILE}" "${MONITORING_TARGET_PATH}"
install -m 0600 "${ACCESS_TMP_FILE}" "${ACCESS_TARGET_PATH}"
chown root:root "${TARGET_PATH}" 2>/dev/null || true
chown root:root "${PROXY_TARGET_PATH}" 2>/dev/null || true
chown root:root "${MONITORING_TARGET_PATH}" 2>/dev/null || true
chown root:root "${ACCESS_TARGET_PATH}" 2>/dev/null || true

rm -f "${TMP_FILE}" "${PROXY_TMP_FILE}" "${MONITORING_TMP_FILE}" "${ACCESS_TMP_FILE}"
trap - EXIT

printf 'Created %s, %s, and %s with generated admin/API/proxy/monitoring secrets.\n' "${TARGET_PATH}" "${PROXY_TARGET_PATH}" "${MONITORING_TARGET_PATH}"
printf 'Operator access values were written to %s.\n' "${ACCESS_TARGET_PATH}"
printf 'Next step: edit optional values such as SENTRY_DSN and ALERT_WEBHOOK_URL manually.\n'
