#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR="${APP_DIR:-/opt/soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
MARKER="${APP_DIR}/backend-recovery-required"
if [[ "${EXPECTED_RELEASE:-}" != "${ROOT_DIR}" ]]; then
  echo 'Requires EXPECTED_RELEASE=<this exact release path>.' >&2
  exit 1
fi
[[ -f "${MARKER}" ]] && grep -Fxq "release=${ROOT_DIR}" "${MARKER}"
grep -Fxq 'phase=pending_acceptance' "${MARKER}" || { echo 'Release has not reached pending acceptance.' >&2; exit 1; }
[[ ! -e "${APP_DIR}/master-qr-activation-required" ]] || { echo 'Master QR activation must be finalized or recovered before infrastructure acceptance.' >&2; exit 1; }
[[ ! -e "${APP_DIR}/english-backfill-required" && ! -L "${APP_DIR}/english-backfill-required" ]] || { echo 'English backfill must be finalized or recovered before infrastructure acceptance.' >&2; exit 1; }
[[ ! -e "${APP_DIR}/shop-online-activation-required" && ! -L "${APP_DIR}/shop-online-activation-required" ]] || { echo 'Shop online activation must be finalized or recovered before infrastructure acceptance.' >&2; exit 1; }
failed_acceptance() {
  local status=$?
  trap - ERR
  python3 "${ROOT_DIR}/scripts/master-mono-dispatch-cutover.py" refence --release "${ROOT_DIR}" || true
  exit "${status}"
}
trap failed_acceptance ERR
bash "${ROOT_DIR}/scripts/verify-release-runtime.sh" "${ROOT_DIR}"
python3 "${ROOT_DIR}/scripts/master-mono-dispatch-cutover.py" accepted --release "${ROOT_DIR}"
ln -sfn "${ROOT_DIR}" "${APP_DIR}/current"
python3 "${ROOT_DIR}/scripts/master-mono-dispatch-cutover.py" switched --release "${ROOT_DIR}"
rm "${MARKER}"
trap - ERR
echo 'Pilot infrastructure accepted; public checkout remains disabled.'
