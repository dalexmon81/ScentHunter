#!/bin/sh
set -eu

if [ -z "${SCENTHUNTER_REDIS_URL:-}" ]; then
  echo "ERROR: SCENTHUNTER_REDIS_URL is missing or empty in the worker runtime."
  exit 1
fi

case "$SCENTHUNTER_REDIS_URL" in
  rediss://*) echo "Redis broker environment detected (TLS); credentials hidden." ;;
  redis://*) echo "Redis broker environment detected (non-TLS); credentials hidden." ;;
  *)
     detected_scheme="$(python -c 'import os; from urllib.parse import urlsplit; print(urlsplit(os.environ.get("SCENTHUNTER_REDIS_URL", "").strip()).scheme or "none")')"
     echo "ERROR: SCENTHUNTER_REDIS_URL has unsupported scheme '$detected_scheme'; expected rediss or redis. Credentials are not logged."
     exit 1 ;;
esac

python - <<'PY'
from sqlalchemy import text
from app.db import make_engine
from app.db_runtime_identity import configuration_source, log_runtime_database_identity
engine = make_engine()
try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        log_runtime_database_identity(connection, event_name="worker_startup_preflight", service_name="celery-staging-worker", config_source=configuration_source())
    print("Phase 2 catalog database connectivity: OK", flush=True)
finally:
    engine.dispose()
PY

process_type="${1:-worker}"
case "$process_type" in
  beat)
    # Keep scheduled discovery/refresh disabled until staging data isolation is reviewed.
    if [ "${SCENTHUNTER_ENABLE_CELERY_BEAT:-false}" != "true" ]; then
      echo "Celery Beat is safely disabled; explicit opt-in required after staging schedule review."
      exec sleep infinity
    fi
    echo "Starting the single staging Celery Beat scheduler."
    exec celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
    ;;
  worker)
    exec celery -A app.workers.celery_app:celery_app worker \
      --loglevel=INFO \
      --queues=discovery,offers,validation,matching,refresh,dead_letter \
      --concurrency=2
    ;;
  *) echo "ERROR: unknown process type '$process_type'"; exit 2 ;;
esac
