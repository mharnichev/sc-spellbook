#!/usr/bin/env bash
# Shared by deploy, rollback and restore. Stale locks require operator inspection.
acquire_release_lock() {
  mkdir -p "${APP_DIR}"
  RELEASE_LOCK="${APP_DIR}/release.lock"
  if ! mkdir "${RELEASE_LOCK}" 2>/dev/null; then
    echo 'Another release/recovery operation holds release.lock; inspect before removing a stale lock.' >&2
    exit 1
  fi
  printf '%s\n' "$$" > "${RELEASE_LOCK}/pid"
  trap 'rm -f "${RELEASE_LOCK}/pid"; rmdir "${RELEASE_LOCK}"' EXIT
}
