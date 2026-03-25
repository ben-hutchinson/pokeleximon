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
echo "  2. Run infra/production/aws-ec2/bin/create_secrets.sh --root ${ROOT}"
echo "  3. Review ${ROOT}/app/deploy.env and ${ROOT}/secrets/api.env"
