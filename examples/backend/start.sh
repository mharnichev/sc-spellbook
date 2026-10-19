#!/bin/sh
set -eu

# Production API is never a migration owner, even with an accidental env override.
if [ "${MIGRATIONS_MODE:-check}" != check ]; then
  echo 'API requires MIGRATIONS_MODE=check; use the isolated release service' >&2
  exit 1
fi
if [ "${API_WORKERS:-1}" != 1 ]; then
  echo 'Pilot API requires exactly one scheduler-owning worker' >&2
  exit 1
fi
export TRUSTED_PROXY_IPS="${TRUSTED_PROXY_IPS:-172.30.41.2}"
python -m app.core.proxy_trust
python -m app.core.migration_readiness
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips "$TRUSTED_PROXY_IPS"
