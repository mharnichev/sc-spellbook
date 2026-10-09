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

compose() {
  docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml "$@"
}

# Reject malformed archives before stopping writers or changing the database.
compose exec -T postgres pg_restore --list < "${BACKUP_FILE}" >/dev/null
writers=()
running_services="$(compose ps --status running --services)"
while IFS= read -r service; do
  case "${service}" in
    backend|booking-sms-reminders) writers+=("${service}") ;;
  esac
done <<< "${running_services}"

if (( ${#writers[@]} )); then
  compose stop "${writers[@]}"
fi
trap 'echo "Restore failed. Database writers remain stopped; investigate before restarting." >&2' ERR

compose exec -T postgres \
  sh -c 'dropdb --if-exists --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'

compose exec -T postgres \
  sh -c 'pg_restore --exit-on-error --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "${BACKUP_FILE}"

trap - ERR
if (( ${#writers[@]} )); then
  compose start "${writers[@]}"
fi

echo "Database restored from ${BACKUP_FILE}"
