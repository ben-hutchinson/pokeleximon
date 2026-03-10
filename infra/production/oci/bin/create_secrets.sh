#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: create_secrets.sh [--root /opt/pokeleximon] [--force]

Creates /opt/pokeleximon/secrets/api.env from the committed template, generates
fresh secrets in place, and locks file permissions. Secret values are never
printed to stdout.
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
SECRETS_DIR="${ROOT}/secrets"
TARGET_PATH="${SECRETS_DIR}/api.env"

if [[ ! -f "${TEMPLATE_PATH}" ]]; then
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

if [[ -f "${TARGET_PATH}" && "${FORCE}" != "true" ]]; then
  printf 'Refusing to overwrite existing secret file: %s\n' "${TARGET_PATH}" >&2
  printf 'Re-run with --force if you intend to rotate all generated secrets.\n' >&2
  exit 1
fi

install -d -m 0700 "${SECRETS_DIR}"

ADMIN_TOKEN="$(generate_secret)"
DB_PASSWORD="$(generate_secret)"

TMP_FILE="$(mktemp "${SECRETS_DIR}/api.env.XXXXXX")"
trap 'rm -f "${TMP_FILE}"' EXIT

cp "${TEMPLATE_PATH}" "${TMP_FILE}"

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

install -m 0600 "${TMP_FILE}" "${TARGET_PATH}"
chown root:root "${TARGET_PATH}" 2>/dev/null || true

rm -f "${TMP_FILE}"
trap - EXIT

printf 'Created %s with generated admin token and database password.\n' "${TARGET_PATH}"
printf 'Next step: edit optional values such as SENTRY_DSN and ALERT_WEBHOOK_URL manually.\n'
