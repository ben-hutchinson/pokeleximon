#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/opt/pokeleximon}"

install -d -m 0755 \
  "${ROOT}" \
  "${ROOT}/app" \
  "${ROOT}/app/releases" \
  "${ROOT}/backups" \
  "${ROOT}/bin" \
  "${ROOT}/data" \
  "${ROOT}/data/artifacts" \
  "${ROOT}/data/caddy/config" \
  "${ROOT}/data/caddy/data" \
  "${ROOT}/data/postgres" \
  "${ROOT}/data/redis"

install -d -m 0700 "${ROOT}/secrets"

chown root:root "${ROOT}/secrets"
chmod 0700 "${ROOT}/secrets"

echo "Created ${ROOT} deployment directories."
echo "Next steps:"
echo "  1. Copy deploy.env.template to ${ROOT}/app/deploy.env"
echo "  2. Copy api.env.template to ${ROOT}/secrets/api.env"
echo "  3. chmod 600 ${ROOT}/secrets/api.env"
