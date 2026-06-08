#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/soulcuts}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_LINK="${APP_DIR}/current"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/versions/production.env"
PREVIOUS_RELEASE=""

compose() {
  docker compose --project-name "${PROJECT_NAME}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

require_file() {
  if [[ ! -f "$1" ]]; then
    echo "Missing required file: $1" >&2
    exit 1
  fi
}

wait_for_service() {
  local service="$1"
  local timeout="${2:-120}"
  local elapsed=0
  local cid status

  echo "Waiting for ${service}..."
  while (( elapsed < timeout )); do
    cid="$(compose ps -q "${service}")"
    if [[ -n "${cid}" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}")"
      if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
        echo "${service} is ${status}"
        return 0
      fi
      if [[ "${status}" == "unhealthy" || "${status}" == "exited" || "${status}" == "dead" ]]; then
        echo "${service} became ${status}" >&2
        compose logs --tail=100 "${service}" >&2 || true
        return 1
      fi
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done

  echo "Timed out waiting for ${service}" >&2
  compose logs --tail=100 "${service}" >&2 || true
  return 1
}

restore_previous_release() {
  if [[ -n "${PREVIOUS_RELEASE}" && -d "${PREVIOUS_RELEASE}" && "${PREVIOUS_RELEASE}" != "${ROOT_DIR}" ]]; then
    echo "Deployment failed. Restoring previous release: ${PREVIOUS_RELEASE}" >&2
    (
      cd "${PREVIOUS_RELEASE}"
      docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml up -d --remove-orphans
    ) || true
    ln -sfn "${PREVIOUS_RELEASE}" "${CURRENT_LINK}"
  fi
}

trap restore_previous_release ERR

require_file "${COMPOSE_FILE}"
require_file "${ENV_FILE}"
require_file "${APP_DIR}/env/caddy.env"
require_file "${APP_DIR}/env/postgres.env"
require_file "${APP_DIR}/env/backend.env"
require_file "${APP_DIR}/env/public-site.env"
require_file "${APP_DIR}/env/blog.env"
require_file "${APP_DIR}/env/admin-app.env"

mkdir -p "${APP_DIR}/data/uploads" "${APP_DIR}/backups" "${APP_DIR}/releases"

if [[ -L "${CURRENT_LINK}" ]]; then
  PREVIOUS_RELEASE="$(readlink -f "${CURRENT_LINK}")"
fi

cd "${ROOT_DIR}"

echo "Validating Compose configuration..."
compose config -q

echo "Pulling images..."
compose pull

echo "Starting services..."
compose up -d --remove-orphans

wait_for_service postgres 120
wait_for_service backend 180
wait_for_service public-site 120
wait_for_service blog 120
wait_for_service admin-app 120
wait_for_service caddy 120

ln -sfn "${ROOT_DIR}" "${CURRENT_LINK}"

echo "Deployment completed: ${ROOT_DIR}"
