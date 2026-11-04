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

exec celery -A app.workers.celery_app:celery_app worker \
  --broker="$SCENTHUNTER_REDIS_URL" \
  --loglevel=INFO \
  --queues=discovery,offers,validation,matching,refresh,dead_letter \
  --concurrency=2
