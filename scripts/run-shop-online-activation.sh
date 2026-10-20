#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=/opt/soulcuts
TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${EXPECTED_RELEASE:?Exact pending release is required}"
MODE="${1:?Activation operation is required}"
case "${MODE}" in apply|reconcile|rollback|recover-finalize|finalize) ;; *) exit 1 ;; esac
python3 - "${APP_DIR}" "${ROOT_DIR}" "${TOOLS_DIR}" <<'PY'
from pathlib import Path
import sys
app,root,tools=map(Path,sys.argv[1:])
if not (root.is_dir() and not root.is_symlink() and root.resolve().parent==(app/'releases').resolve() and tools.resolve()==root.resolve()/'scripts'):
    raise SystemExit('Invalid candidate/tool directory')
PY
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
export RELEASE_LOCK_OWNER_PID=$$
python3 - "${APP_DIR}" "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
app,root=map(Path,sys.argv[1:])
marker=dict(line.split('=',1) for line in (app/'backend-recovery-required').read_text().splitlines())
if marker.get('release')!=str(root) or marker.get('phase')!='pending_acceptance':
    raise SystemExit('Exact pending backend release is required')
PY
PIN="$(python3 "${ROOT_DIR}/scripts/release-backend-pin.py" "${ROOT_DIR}/versions/production.env")"
if [[ -z "${EXPECTED_BACKEND_IMAGE:-}" || "${PIN}" != "${EXPECTED_BACKEND_IMAGE}" ]]; then
  echo 'Unexpected candidate pin; no writers stopped.' >&2
  exit 1
fi
export BACKEND_IMAGE="${PIN}"
export BACKEND_ENV_FILE="${APP_DIR}/env/backend.env"
export POSTGRES_ENV_FILE="${APP_DIR}/env/postgres.env"
compose() {
  docker compose --project-name soulcuts --env-file "${ROOT_DIR}/versions/production.env" -f "${ROOT_DIR}/docker-compose.prod.yml" "$@"
}
STARTED=false
failed() {
  local status=$?
  trap - ERR HUP INT TERM
  if [[ "${STARTED}" == true ]]; then
    if ! compose stop --timeout 90 backend booking-sms-reminders; then
      echo 'CRITICAL: writer cleanup failed; retain backend fence and inspect private state.' >&2
    fi
    if ! python3 - "${TOOLS_DIR}" <<'PY'
import importlib.util,sys
from pathlib import Path
tools=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('shop_activation_cleanup',tools/'activate-shop-online.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root,_=module.release_context()
module.cleanup_release(root)
PY
    then
      echo 'CRITICAL: read-only task cleanup failed; retain backend fence.' >&2
    fi
  fi
  exit "${status}"
}
interrupted() { false; }
trap failed ERR
trap interrupted HUP INT TERM
STARTED=true
if [[ "${MODE}" != finalize ]]; then
  compose stop --timeout 90 backend booking-sms-reminders
fi
python3 "${TOOLS_DIR}/activate-shop-online.py" "$@"
if [[ "${MODE}" == apply || "${MODE}" == reconcile || "${MODE}" == recover-finalize ]]; then
  python3 - "${APP_DIR}" "${ROOT_DIR}" "${MODE}" "${2:-}" <<'PY'
import hashlib,json,sys
from pathlib import Path
app,root=map(Path,sys.argv[1:3])
marker=app/'shop-online-activation-required'
state=json.loads(marker.read_text()) if marker.exists() else json.loads((Path(sys.argv[4])/'finalized.json').read_text())['state']
if state['release']!=str(root) or state.get('pre_restart_original_verified') is not True or hashlib.sha256((app/'env/backend.env').read_bytes()).hexdigest()!=state['after_sha256']:
    raise SystemExit('Environment drift; writers remain stopped')
for name,expected in state['tools'].items():
    if hashlib.sha256((root/'scripts'/name).read_bytes()).hexdigest()!=expected:
        raise SystemExit('Tool drift; writers remain stopped')
PY
  compose up -d --no-deps --pull never --no-build backend booking-sms-reminders
fi
