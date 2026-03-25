#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: configure_swap.sh [--size 2G] [--path /swapfile]

Creates or resizes a swapfile, enables it immediately, and persists it in
/etc/fstab. Intended for small single-host EC2 deployments.
EOF
}

SWAP_SIZE="2G"
SWAP_PATH="/swapfile"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --size)
      SWAP_SIZE="$2"
      shift 2
      ;;
    --path)
      SWAP_PATH="$2"
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

if [[ $EUID -ne 0 ]]; then
  printf 'Run as root.\n' >&2
  exit 1
fi

if swapon --show=NAME --noheadings | grep -Fxq "${SWAP_PATH}"; then
  swapoff "${SWAP_PATH}"
fi

rm -f "${SWAP_PATH}"
fallocate -l "${SWAP_SIZE}" "${SWAP_PATH}"
chmod 600 "${SWAP_PATH}"
mkswap "${SWAP_PATH}" >/dev/null
swapon "${SWAP_PATH}"

if grep -qE "^[^#]*[[:space:]]${SWAP_PATH//\//\\/}[[:space:]]" /etc/fstab; then
  sed -i "\|^[^#]*[[:space:]]${SWAP_PATH}[[:space:]]|d" /etc/fstab
fi
printf '%s none swap sw 0 0\n' "${SWAP_PATH}" >> /etc/fstab

sysctl -w vm.swappiness=10 >/dev/null
if grep -q '^vm.swappiness=' /etc/sysctl.conf; then
  sed -i 's/^vm\.swappiness=.*/vm.swappiness=10/' /etc/sysctl.conf
else
  printf '\nvm.swappiness=10\n' >> /etc/sysctl.conf
fi

printf 'Configured swapfile %s (%s).\n' "${SWAP_PATH}" "${SWAP_SIZE}"
swapon --show
