#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/soulcuts}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/soulcuts-postgres-${STAMP}.dump"
TMP_OUT=""

mkdir -p "${BACKUP_DIR}"
[[ ! -e "${OUT}" ]] || { echo 'Backup already exists' >&2; exit 1; }
TMP_OUT="$(mktemp "${BACKUP_DIR}/.soulcuts-db.XXXXXX")"
trap 'rm -f "${TMP_OUT}"' EXIT

cd "${ROOT_DIR}"

docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_dump -Fc --lock-wait-timeout=5s -U "$POSTGRES_USER" "$POSTGRES_DB"' > "${TMP_OUT}"

[[ -s "${TMP_OUT}" ]] || { echo 'Empty database backup' >&2; exit 1; }
docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml exec -T postgres \
  pg_restore --list < "${TMP_OUT}" >/dev/null

mv "${TMP_OUT}" "${OUT}"
chmod 0600 "${OUT}"
echo "Backup written to ${OUT}"
