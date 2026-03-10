#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PATTERN='(ADMIN_AUTH_TOKEN=|VITE_ADMIN_API_TOKEN=|DATABASE_URL=.*:.*@|REDIS_URL=redis://.*:.*@|BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY)'
ALLOWLIST='(^services/api/\.env:|^services/api/\.env\.example:|^services/api/\.env\.ec2\.example:|^apps/web/\.env\.example:|^infra/production/oci/env/api\.env\.template:|^infra/production/oci/RUNBOOK\.md:|^\.github/workflows/deploy-oci\.yml:|^\.github/workflows/playwright\.yml:|^README\.md:)'

RESULTS="$(git grep -nE "${PATTERN}" -- . || true)"

if [[ -z "${RESULTS}" ]]; then
  printf 'No secret-like patterns found in tracked files.\n'
  exit 0
fi

FILTERED="$(printf '%s\n' "${RESULTS}" | grep -vE "${ALLOWLIST}" || true)"

if [[ -n "${FILTERED}" ]]; then
  printf 'Potential secret-like patterns found:\n%s\n' "${FILTERED}" >&2
  exit 1
fi

printf 'Only allowed template/example secret-like patterns found.\n'
