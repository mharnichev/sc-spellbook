#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR="${APP_DIR:-/opt/soulcuts}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_LINK="${APP_DIR}/current"
RECOVERY_MARKER="${APP_DIR}/backend-recovery-required"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/versions/production.env"
WRITERS_STOPPING=false
compose() {
  docker compose --project-name "${PROJECT_NAME}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}
preflight_sentry_store() {
  local runtime_uid
  runtime_uid="$(docker run --rm --pull=never --network none --entrypoint python "${next_backend}" -c 'import os; print(os.geteuid())')"
  python3 "${ROOT_DIR}/scripts/check-sentry-incident-store.py" "${runtime_uid}"
  docker run --rm --interactive --pull=never --network none --read-only \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 32 --memory 64m --cpus 0.5 \
    --mount type=bind,src=/opt/soulcuts/data/sentry-incidents,dst=/state,readonly \
    --entrypoint python "${next_backend}" - --runtime-store \
    < "${ROOT_DIR}/scripts/check-sentry-incident-store.py"
}
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
[[ -L "${CURRENT_LINK}" ]] || { echo 'An existing current release is required; bootstrap is a separate procedure.' >&2; exit 1; }
PREVIOUS_RELEASE="$(readlink -f "${CURRENT_LINK}")"
previous_backend="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${PREVIOUS_RELEASE}/versions/production.env")"
next_backend="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${ENV_FILE}")"
BACKEND_CHANGED=false
[[ "${previous_backend}" == "${next_backend}" ]] || BACKEND_CHANGED=true
# Release pins, not inherited shell overrides, define backend-change ownership.
export BACKEND_IMAGE="${next_backend}"
REQUIRED_SCOPE=""
admin_only_image=""
if [[ -f "${ROOT_DIR}/versions/deploy.scope" ]]; then
  REQUIRED_SCOPE="$(cat "${ROOT_DIR}/versions/deploy.scope")"
  [[ "${REQUIRED_SCOPE}" == admin-app ]] || { echo 'Unsupported required deployment scope.' >&2; exit 1; }
  admin_only_image="$(python3 "${ROOT_DIR}/scripts/admin-only-release.py" "${PREVIOUS_RELEASE}" "${ROOT_DIR}" --allow-unchanged)"
  [[ -n "${admin_only_image}" ]] || { echo 'Admin-only scope refused: other pins or shared configuration differ or are unavailable.' >&2; exit 1; }
fi
failed() {
  local status=$?
  trap - ERR
  if [[ "${WRITERS_STOPPING}" == true ]]; then
    echo 'Deployment failed. Refusing automatic image rollback; database writers remain stopped.' >&2
    compose stop --timeout 90 backend booking-sms-reminders || true
    echo "Recovery marker retained: ${RECOVERY_MARKER}" >&2
  fi
  exit "${status}"
}
trap failed ERR
if [[ -e "${RECOVERY_MARKER}" ]]; then
  echo 'Backend recovery is required; reconcile schema, queues and release before clearing the marker.' >&2
  exit 1
fi
for file in "${COMPOSE_FILE}" "${ENV_FILE}"; do
  [[ -f "${file}" ]] || { echo "Missing required file: ${file}" >&2; exit 1; }
done
for name in caddy postgres backend public-site blog admin-app shop; do
  [[ -f "${APP_DIR}/env/${name}.env" ]] || { echo "Missing ${name} environment file" >&2; exit 1; }
done
[[ -d "${APP_DIR}/data/uploads" ]] || { echo 'Missing persistent uploads directory' >&2; exit 1; }
cd "${ROOT_DIR}"
compose config -q
python3 "${ROOT_DIR}/scripts/verify-deployed-images.py" --pins-only
python3 "${ROOT_DIR}/scripts/check-ingress-network.py" "${PROJECT_NAME}_api_ingress"
export APP_DIR COMPOSE_PROJECT_NAME="${PROJECT_NAME}"
if [[ "${BACKEND_CHANGED}" == true ]]; then
compose --profile release pull
preflight_sentry_store
# Reject the still-pinned old backend before touching running writers.
compose --profile release run --rm --no-deps --entrypoint python migrate -c \
  'try:
    from app.core.config import Settings
    Settings()
    import app.core.proxy_trust
    import app.core.migration_readiness
    import app.core.background_workers
    import app.services.master_mono
    import app.services.mono_checkbox_poll
    import app.utils.backfill_product_names_en
    import app.utils.backfill_category_names_en
    import app.services.shop_online_payment
    import app.utils.backfill_shop_content_en
    import app.dependencies.shop_input
    import app.core.shop_request_size
    import app.services.checkout_reminders
    import app.services.checkout_reminder_email
    import app.services.checkout_reminder_smtp
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    if ScriptDirectory.from_config(Config("alembic.ini")).get_heads() != ["0143_auto_checkout_checkpoint"]:
        raise RuntimeError("Unexpected migration head")
except Exception:
    raise SystemExit("Backend release preflight failed: settings, modules or schema contract unavailable") from None'
mkdir -p "${APP_DIR}/backups" "${APP_DIR}/releases"
BACKUP_DIR="$(mktemp -d "${APP_DIR}/backups/pilot-XXXXXXXX")"
export BACKUP_DIR
printf 'release=%s\nbackup=%s\n' "${ROOT_DIR}" "${BACKUP_DIR}" > "${RECOVERY_MARKER}"
WRITERS_STOPPING=true
compose stop --timeout 90 booking-sms-reminders backend
remaining="$(compose ps --status running --services)"
if printf '%s\n' "${remaining}" | grep -Eq '^(backend|booking-sms-reminders)$'; then
  echo 'Database writers did not stop' >&2
  false
fi
bash "${ROOT_DIR}/scripts/backup-db.sh"
bash "${ROOT_DIR}/scripts/backup-files.sh"
python3 "${ROOT_DIR}/scripts/backup-manifest.py" "${BACKUP_DIR}"
compose --profile release run --rm --no-deps migrate
compose --profile release run --rm --no-deps --entrypoint python migrate -m app.core.migration_readiness
compose up -d --remove-orphans
else
  if [[ -z "${REQUIRED_SCOPE}" ]]; then
    admin_only_image="$(python3 "${ROOT_DIR}/scripts/admin-only-release.py" "${PREVIOUS_RELEASE}" "${ROOT_DIR}")"
  fi
  if [[ -n "${admin_only_image}" ]]; then
    export ADMIN_APP_IMAGE="${admin_only_image}"
    compose pull admin-app
  else
    compose pull public-site blog admin-app shop caddy
  fi
  # Do not recreate API/reminders or apply backend config on frontend-only releases.
  compose exec -T backend python -m app.core.migration_readiness
  if [[ -n "${admin_only_image}" ]]; then
    # Caddy can keep its previous release mount: its bytes and Compose are identical.
    compose up -d --no-deps admin-app
  else
    compose up -d --no-deps public-site blog admin-app shop caddy
  fi
fi
for service in postgres backend booking-sms-reminders public-site blog admin-app shop caddy; do
  healthy=false
  for ((attempt=0; attempt<36; attempt++)); do
    cid="$(compose ps -q "${service}")"
    if [[ -n "${cid}" ]]; then
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}")"
      case "${state}" in
        healthy|running) healthy=true; break ;;
        unhealthy|exited|dead) break ;;
      esac
    fi
    sleep 5
  done
  if [[ "${healthy}" != true ]]; then echo "Service not ready: ${service}" >&2; false; fi
done
bash "${ROOT_DIR}/scripts/verify-background-owner.sh"
python3 "${ROOT_DIR}/scripts/verify-deployed-images.py"
if [[ "${BACKEND_CHANGED}" == false ]]; then
  ln -sfn "${ROOT_DIR}" "${CURRENT_LINK}"
  echo "Frontend-only deployment completed: ${ROOT_DIR}; backend and writers unchanged."
  exit 0
fi
printf 'phase=pending_acceptance\n' >> "${RECOVERY_MARKER}"
trap - ERR
echo "Services started, NOT ACCEPTED: ${ROOT_DIR}. Recovery marker retained."
echo 'Primary must verify authenticated watch scheduler names, queue progress and reminder utility, then run accept-shop-pilot.sh.'
exit 3
