#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose() {
  docker compose --project-name "${COMPOSE_PROJECT_NAME:-soulcuts}" --env-file "${ROOT_DIR}/versions/production.env" -f "${ROOT_DIR}/docker-compose.prod.yml" "$@"
}
cid="$(compose ps -q backend)"
[[ -n "${cid}" && "${cid}" != *$'\n'* ]] || { echo 'Expected exactly one API container' >&2; exit 1; }
started="$(docker inspect -f '{{.State.StartedAt}}' "${cid}")"
[[ -n "${started}" ]] || { echo 'API start timestamp unavailable' >&2; exit 1; }
docker logs --since "${started}" "${cid}" 2>&1 | python3 "${ROOT_DIR}/scripts/verify-background-owner.py"
# Only read the existing owner's lock. This process never acquires ownership.
compose exec -T backend python -c '
from sqlalchemy import create_engine, text
from app.core.config import settings
engine=None
try:
    engine=create_engine(settings.sqlalchemy_sync_database_uri, connect_args={"connect_timeout":5,"options":"-c statement_timeout=5000"})
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        count=connection.execute(text("SELECT count(*) FROM pg_locks WHERE locktype=\047advisory\047 AND granted AND classid=1396919372 AND objid=1 AND objsubid=2 AND database=(SELECT oid FROM pg_database WHERE datname=current_database())")).scalar_one()
        if count != 1:
            raise SystemExit("Background owner lock missing or ambiguous")
except Exception:
    raise SystemExit("Background owner DB verification failed") from None
finally:
    if engine is not None:
        engine.dispose()
'
# Detect an intervening owner failure or container restart before accepting.
[[ "$(compose ps -q backend)" == "${cid}" && "$(docker inspect -f '{{.State.StartedAt}}' "${cid}")" == "${started}" ]]
docker logs --since "${started}" "${cid}" 2>&1 | python3 "${ROOT_DIR}/scripts/verify-background-owner.py"
