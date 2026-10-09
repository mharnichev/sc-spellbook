#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/soulcuts}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/soulcuts-files-${STAMP}.tar.gz"
TMP_OUT=""

[[ -d "${APP_DIR}/data/uploads" ]] || { echo "Missing uploads directory" >&2; exit 1; }
mkdir -p "${BACKUP_DIR}"
[[ ! -e "${OUT}" ]] || { echo "Backup already exists: ${OUT}" >&2; exit 1; }
TMP_OUT="$(mktemp "${BACKUP_DIR}/.soulcuts-files.XXXXXX")"
trap 'rm -f "${TMP_OUT}"' EXIT
directories=(uploads)
[[ ! -d "${APP_DIR}/data/imports" ]] || directories+=(imports)

tar -czf "${TMP_OUT}" -C "${APP_DIR}/data" "${directories[@]}"
tar -tzf "${TMP_OUT}" >/dev/null
mv "${TMP_OUT}" "${OUT}"
echo "File backup written to ${OUT}"
