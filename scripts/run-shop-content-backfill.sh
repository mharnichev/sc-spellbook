#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=/opt/soulcuts
TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${EXPECTED_RELEASE:?Exact pending release is required}"
MODE="${1:?Content backfill operation is required}"
case "${MODE}" in apply|reconcile|rollback|recover-finalize|finalize) ;; *) exit 1 ;; esac
[[ "${TOOLS_DIR}" == "${ROOT_DIR}/scripts" ]] || exit 1
python3 - "${APP_DIR}" "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
app,root=map(Path,sys.argv[1:])
if not (root.is_dir() and not root.is_symlink() and root.resolve().parent==(app/'releases').resolve()):
    raise SystemExit('Invalid content release')
PY
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
export RELEASE_LOCK_OWNER_PID=$$
PIN="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${ROOT_DIR}/versions/production.env")"
[[ -n "${EXPECTED_BACKEND_IMAGE:-}" && "${PIN}" == "${EXPECTED_BACKEND_IMAGE}" ]] || exit 1
python3 - "${APP_DIR}" "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
app,root=map(Path,sys.argv[1:])
if not (root.is_dir() and not root.is_symlink() and root.resolve().parent==(app/'releases').resolve()):
    raise SystemExit('Invalid content release')
marker=dict(line.split('=',1) for line in (app/'backend-recovery-required').read_text().splitlines())
if marker.get('release')!=str(root) or marker.get('phase')!='pending_acceptance':
    raise SystemExit('Exact pending backend release is required')
PY
unset PUBLIC_SITE_IMAGE BLOG_IMAGE ADMIN_APP_IMAGE SHOP_IMAGE CADDY_IMAGE POSTGRES_IMAGE
export BACKEND_IMAGE="${PIN}"
export BACKEND_ENV_FILE="${APP_DIR}/env/backend.env"
export POSTGRES_ENV_FILE="${APP_DIR}/env/postgres.env"
compose() {
  docker compose --project-name soulcuts --env-file "${ROOT_DIR}/versions/production.env" -f "${ROOT_DIR}/docker-compose.prod.yml" "$@"
}
STARTED=false
failed() {
  local status="${1:-$?}"
  trap - ERR HUP INT TERM
  if [[ "${STARTED}" == true ]]; then
    compose stop --timeout 90 backend booking-sms-reminders || echo 'CRITICAL: writer cleanup failed; retain fences.' >&2
    python3 - "${TOOLS_DIR}" "${ROOT_DIR}" <<'PY' || echo 'CRITICAL: content task cleanup failed; retain fences.' >&2
import importlib.util,sys
from pathlib import Path
tools,root=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('content_cleanup',tools/'apply-shop-content-backfill.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.cleanup_release(root)
PY
  fi
  exit "${status}"
}
trap failed ERR
trap 'failed 129' HUP
trap 'failed 130' INT
trap 'failed 143' TERM
STARTED=true
if [[ "${MODE}" != finalize ]]; then
  compose stop --timeout 90 backend booking-sms-reminders
fi
python3 "${TOOLS_DIR}/apply-shop-content-backfill.py" "$@"
if [[ "${MODE}" == apply || "${MODE}" == reconcile || "${MODE}" == recover-finalize ]]; then
  python3 - "${APP_DIR}" "${ROOT_DIR}" "${2:-}" <<'PY'
import hashlib,json,sys
from pathlib import Path
app,root=map(Path,sys.argv[1:3])
marker=app/'english-backfill-required'
state=json.loads(marker.read_text()) if marker.exists() else json.loads((Path(sys.argv[3])/'finalized.json').read_text())['state']
if state['release']!=str(root) or state.get('pre_restart_original_verified') is not True or hashlib.sha256((app/'env/backend.env').read_bytes()).hexdigest()!=state['env_sha256']:
    raise SystemExit('Content provenance drift; writers remain stopped')
for name,expected in state['tools'].items():
    if hashlib.sha256((root/'scripts'/name).read_bytes()).hexdigest()!=expected:
        raise SystemExit('Content tool drift; writers remain stopped')
PY
  compose up -d --no-deps --pull never --no-build backend booking-sms-reminders
fi
