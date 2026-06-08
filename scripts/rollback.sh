#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/soulcuts}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
CURRENT_LINK="${APP_DIR}/current"
RELEASES_DIR="${APP_DIR}/releases"
TARGET="${1:-}"

compose() {
  docker compose --project-name "${PROJECT_NAME}" --env-file versions/production.env -f docker-compose.prod.yml "$@"
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

if [[ -z "${TARGET}" ]]; then
  current="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  TARGET="$(find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d | sort -r | while read -r release; do
    if [[ "$(readlink -f "${release}")" != "${current}" ]]; then
      echo "${release}"
      break
    fi
  done)"
fi

if [[ -z "${TARGET}" || ! -d "${TARGET}" ]]; then
  echo "Rollback target not found. Pass a release path explicitly." >&2
  exit 1
fi

cd "${TARGET}"

compose config -q
compose up -d --remove-orphans

wait_for_service postgres 120
wait_for_service backend 180
wait_for_service public-site 120
wait_for_service blog 120
wait_for_service admin-app 120
wait_for_service caddy 120

ln -sfn "${TARGET}" "${CURRENT_LINK}"

echo "Rolled back to ${TARGET}"
