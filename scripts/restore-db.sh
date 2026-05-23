#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/soulcuts}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_FILE="${1:-}"

if [[ "${CONFIRM_RESTORE:-}" != "production" ]]; then
  echo "Refusing to restore without CONFIRM_RESTORE=production" >&2
  exit 1
fi

if [[ -z "${BACKUP_FILE}" || ! -f "${BACKUP_FILE}" ]]; then
  echo "Usage: CONFIRM_RESTORE=production $0 /opt/soulcuts/backups/file.dump" >&2
  exit 1
fi

cd "${ROOT_DIR}"

start_backend() {
  docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml up -d backend || true
}

docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml stop backend
trap start_backend EXIT

docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml exec -T postgres \
  sh -c 'dropdb --if-exists --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'

docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "${BACKUP_FILE}"

trap - EXIT
docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml up -d backend

echo "Database restored from ${BACKUP_FILE}"
