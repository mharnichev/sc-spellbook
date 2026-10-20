#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
APP_DIR=/opt/soulcuts
TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${EXPECTED_RELEASE:?Exact original pending release is required}"
MODE="${1:?apply or reconcile is required}"
STATE_DIR="${2:?Original activation state directory is required}"
[[ "$#" == 2 ]] || exit 1
case "${MODE}" in apply|reconcile) ;; *) exit 1 ;; esac
python3 - "${APP_DIR}" "${ROOT_DIR}" "${TOOLS_DIR}" <<'PY'
import hashlib,os,re,stat,sys
from pathlib import Path
app,root,tools=map(Path,sys.argv[1:])
if not (root.is_dir() and not root.is_symlink() and root.resolve().parent==(app/'releases').resolve()):
    raise SystemExit('Invalid original release')
info=tools.stat()
if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
    raise SystemExit('Private reviewed staging is required')
for name,key in (('recover-shop-online-compose.py','SHOP_ONLINE_COMPOSE_HELPER_SHA256'),('run-shop-online-compose-recovery.sh','SHOP_ONLINE_COMPOSE_WRAPPER_SHA256')):
    path=tools/name
    info=path.lstat()
    expected=os.environ.get(key,'')
    if not (stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid() and stat.S_IMODE(info.st_mode)==0o600 and re.fullmatch('[0-9a-f]{64}',expected) and hashlib.sha256(path.read_bytes()).hexdigest()==expected):
        raise SystemExit('Reviewed recovery tool mismatch')
PY
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
export RELEASE_LOCK_OWNER_PID=$$
PIN="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${ROOT_DIR}/versions/production.env")"
if [[ -z "${EXPECTED_BACKEND_IMAGE:-}" || "${PIN}" != "${EXPECTED_BACKEND_IMAGE}" ]]; then
  echo 'Unexpected original backend pin; writers unchanged.' >&2
  exit 1
fi
unset PUBLIC_SITE_IMAGE BLOG_IMAGE ADMIN_APP_IMAGE SHOP_IMAGE CADDY_IMAGE POSTGRES_IMAGE
export BACKEND_IMAGE="${PIN}"
export BACKEND_ENV_FILE="${APP_DIR}/env/backend.env"
export POSTGRES_ENV_FILE="${APP_DIR}/env/postgres.env"
export CADDY_ENV_FILE="${APP_DIR}/env/caddy.env"
export PUBLIC_SITE_ENV_FILE="${APP_DIR}/env/public-site.env"
export BLOG_ENV_FILE="${APP_DIR}/env/blog.env"
export ADMIN_APP_ENV_FILE="${APP_DIR}/env/admin-app.env"
export SHOP_ENV_FILE="${APP_DIR}/env/shop.env"
STATE_NAME="${STATE_DIR##*/}"
RECOVERY_DIR="${APP_DIR}/backups/shop-online-compose-recovery-${STATE_NAME#shop-online-activation-}"
base_compose() {
  docker compose --project-name soulcuts --env-file "${ROOT_DIR}/versions/production.env" -f "${ROOT_DIR}/docker-compose.prod.yml" "$@"
}
STARTED=false
failed() {
  local status=$?
  trap - ERR HUP INT TERM
  if [[ "${STARTED}" == true ]]; then
    if ! base_compose stop --timeout 90 backend booking-sms-reminders; then
      echo 'CRITICAL: stop failed; retain both fences and inspect containers.' >&2
    fi
  fi
  exit "${status}"
}
interrupted() { false; }
trap failed ERR
trap interrupted HUP INT TERM
# The journal and full config evidence must be durable before touching writers.
if [[ "${MODE}" == apply ]]; then
  python3 "${TOOLS_DIR}/recover-shop-online-compose.py" prepare "${STATE_DIR}"
else
  python3 "${TOOLS_DIR}/recover-shop-online-compose.py" reconcile "${STATE_DIR}"
fi
STARTED=true
base_compose stop --timeout 90 backend booking-sms-reminders
python3 "${TOOLS_DIR}/recover-shop-online-compose.py" after-stop "${STATE_DIR}"
python3 "${TOOLS_DIR}/recover-shop-online-compose.py" before-restart "${STATE_DIR}"
docker compose --project-name soulcuts --env-file "${ROOT_DIR}/versions/production.env" \
  -f "${ROOT_DIR}/docker-compose.prod.yml" -f "${RECOVERY_DIR}/overlay.yml" \
  up -d --no-deps --pull never --no-build backend booking-sms-reminders
python3 "${TOOLS_DIR}/recover-shop-online-compose.py" record-restart "${STATE_DIR}"
echo 'Overlay restart returned; NOT ACCEPTED. Retain both fences for primary runtime verification.'
