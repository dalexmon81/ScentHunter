#!/bin/sh
set -eu

cd /app/backend
exec python -m uvicorn catalog_first_api:app --host 0.0.0.0 --port 8080
