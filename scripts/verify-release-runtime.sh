#!/usr/bin/env bash
# Run against a staged or current release directory on the Docker host.
set -Eeuo pipefail

if [[ $# -ne 1 || ! -d "$1" ]]; then
  echo "Usage: bash verify-release-runtime.sh <release-directory>" >&2
  exit 2
fi
release="$(cd "$1" && pwd -P)"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-soulcuts}"
cd "$release"

compose() {
  docker compose --project-name "$COMPOSE_PROJECT_NAME" \
    --env-file versions/production.env -f docker-compose.prod.yml "$@"
}

python3 -B scripts/verify-deployed-images.py </dev/null
compose exec -T backend python -m app.core.migration_readiness </dev/null
bash scripts/verify-background-owner.sh </dev/null

reminder="$(compose ps -q booking-sms-reminders)"
if [[ -z "$reminder" || "$reminder" == *$'\n'* ]]; then
  echo "Expected exactly one reminder container" >&2
  exit 1
fi
reminder_state="$(docker inspect -f '{{.State.Status}} {{.State.StartedAt}} {{.RestartCount}}' "$reminder")"
read -r status started restarts <<< "$reminder_state"
if [[ "$status" != running || -z "$started" || ! "$restarts" =~ ^[0-9]+$ ]]; then
  echo "Reminder process is not running" >&2
  exit 1
fi
error_lines="$(docker logs --since "$started" "$reminder" 2>&1 |
  awk 'tolower($0) ~ /traceback|error|exception/ { n++ } END { print n+0 }')"
printf 'Reminder process: running, restarts=%s, matching error log lines=%s\n' "$restarts" "$error_lines"

compose exec -T backend python - <<'PY'
from sqlalchemy import create_engine, text
from app.core.config import settings

engine = None
try:
    engine = create_engine(
        settings.sqlalchemy_sync_database_uri,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        for label, query in (
            ("SMS queue", "SELECT status, count(*) FROM sms_queue_jobs GROUP BY status ORDER BY status"),
            ("Checkout reminders", "SELECT state, count(*) FROM checkout_reminders GROUP BY state ORDER BY state"),
        ):
            rows = connection.execute(text(query))
            print(f"{label}: " + (", ".join(f"{state}={count}" for state, count in rows) or "empty"))
except Exception:
    raise SystemExit("Read-only queue summary failed") from None
finally:
    if engine is not None:
        engine.dispose()
PY

if [[ "$(compose ps -q booking-sms-reminders)" != "$reminder" ||
      "$(docker inspect -f '{{.State.Status}} {{.State.StartedAt}} {{.RestartCount}}' "$reminder")" != "$reminder_state" ]]; then
  echo "Reminder process changed during verification" >&2
  exit 1
fi
echo 'Runtime probes passed. Queue counts and reminder log counts are operational signals.'
