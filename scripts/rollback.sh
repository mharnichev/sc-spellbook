#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
[[ ! -e "${APP_DIR}/backend-recovery-required" ]] || { echo 'Backend recovery is required; rollback refused.' >&2; exit 1; }
[[ -L "${APP_DIR}/current" ]] || { echo 'Current release is required' >&2; exit 1; }
CURRENT="$(readlink -f "${APP_DIR}/current")"
TARGET="${1:-}"
[[ -n "${TARGET}" && -d "${TARGET}" ]] || { echo 'Pass an explicit existing frontend rollback release' >&2; exit 1; }
TARGET="$(cd "${TARGET}" && pwd)"
current_pin="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${CURRENT}/versions/production.env")"
target_pin="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${TARGET}/versions/production.env")"
[[ "${current_pin}" == "${target_pin}" ]] || { echo 'Backend image differs; automatic schema/image rollback is forbidden.' >&2; exit 1; }
export BACKEND_IMAGE="${current_pin}"
compose() {
  docker compose --project-name "${COMPOSE_PROJECT_NAME:-soulcuts}" --env-file "${TARGET}/versions/production.env" -f "${TARGET}/docker-compose.prod.yml" "$@"
}
compose config -q
python3 "${ROOT_DIR}/scripts/verify-deployed-images.py" --pins-only "${TARGET}"
compose exec -T backend python -m app.core.migration_readiness
bash "${CURRENT}/scripts/verify-background-owner.sh"
compose up -d --no-deps public-site blog admin-app shop caddy
for service in public-site blog admin-app shop caddy; do
  ready=false
  for ((attempt=0; attempt<24; attempt++)); do
    cid="$(compose ps -q "${service}")"
    if [[ -n "${cid}" ]]; then
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}")"
      case "${state}" in healthy|running) ready=true; break;; unhealthy|exited|dead) break;; esac
    fi
    sleep 5
  done
  [[ "${ready}" == true ]] || { echo "Frontend rollback health failed: ${service}; manual recovery required" >&2; exit 1; }
done
bash "${CURRENT}/scripts/verify-background-owner.sh"
python3 "${ROOT_DIR}/scripts/verify-deployed-images.py" "${TARGET}"
ln -sfn "${TARGET}" "${APP_DIR}/current"
echo 'Frontend-only rollback completed; backend/schema/writers unchanged.'
