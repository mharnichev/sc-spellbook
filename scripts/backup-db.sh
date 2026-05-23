#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/soulcuts}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/soulcuts-postgres-${STAMP}.dump"
TMP_OUT="${OUT}.tmp"

mkdir -p "${BACKUP_DIR}"
trap 'rm -f "${TMP_OUT}"' ERR

cd "${ROOT_DIR}"

docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "${TMP_OUT}"

mv "${TMP_OUT}" "${OUT}"
chmod 0600 "${OUT}"
echo "Backup written to ${OUT}"
