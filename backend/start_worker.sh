#!/bin/sh
set -eu

if [ -z "${SCENTHUNTER_REDIS_URL:-}" ]; then
  echo "ERROR: SCENTHUNTER_REDIS_URL is missing or empty in the worker runtime."
  exit 1
fi

case "$SCENTHUNTER_REDIS_URL" in
  rediss://*) echo "Redis broker environment detected (TLS); credentials hidden." ;;
  redis://*) echo "Redis broker environment detected (non-TLS); credentials hidden." ;;
  *) echo "ERROR: SCENTHUNTER_REDIS_URL has an unsupported URL scheme."
     exit 1 ;;
esac

exec celery -A app.workers.celery_app:celery_app worker \
  --broker="$SCENTHUNTER_REDIS_URL" \
  --loglevel=INFO \
  --queues=discovery,offers,validation,matching,refresh,dead_letter \
  --concurrency=2
