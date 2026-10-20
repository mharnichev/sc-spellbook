#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR="${APP_DIR:-/opt/soulcuts}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/release-lock.sh"
acquire_release_lock
MARKER="${APP_DIR}/backend-recovery-required"
if [[ "${PILOT_MANUAL_GATE:-}" != verified || "${EXPECTED_RELEASE:-}" != "${ROOT_DIR}" ]]; then
  echo 'Requires PILOT_MANUAL_GATE=verified and EXPECTED_RELEASE=<this exact release path> after documented manual checks.' >&2
  exit 1
fi
[[ -f "${MARKER}" ]] && grep -Fxq "release=${ROOT_DIR}" "${MARKER}"
grep -Fxq 'phase=pending_acceptance' "${MARKER}" || { echo 'Release has not reached pending acceptance.' >&2; exit 1; }
[[ ! -e "${APP_DIR}/master-qr-activation-required" ]] || { echo 'Master QR activation must be finalized or recovered before infrastructure acceptance.' >&2; exit 1; }
[[ ! -e "${APP_DIR}/english-backfill-required" && ! -L "${APP_DIR}/english-backfill-required" ]] || { echo 'English backfill must be finalized or recovered before infrastructure acceptance.' >&2; exit 1; }
bash "${ROOT_DIR}/scripts/verify-background-owner.sh"
python3 "${ROOT_DIR}/scripts/verify-deployed-images.py"
ln -sfn "${ROOT_DIR}" "${APP_DIR}/current"
rm "${MARKER}"
echo 'Pilot infrastructure accepted; public checkout remains disabled.'
