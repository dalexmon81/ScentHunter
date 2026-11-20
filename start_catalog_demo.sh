#!/usr/bin/env bash
set -euo pipefail

# Render service root is the repository root. Keep this isolated from the
# legacy main.py runtime and use an ephemeral SQLite catalog for the first UI
# smoke test; no production database or retailer crawler is touched.
cd "$(dirname "$0")/backend"

export SCENTHUNTER_CATALOG_DATABASE_URL="${SCENTHUNTER_CATALOG_DATABASE_URL:-sqlite:////tmp/scenthunter-demo.sqlite3}"
export SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=0

alembic upgrade head
python scripts/seed_catalog.py --apply
exec uvicorn catalog_demo_app:app --host 0.0.0.0 --port "${PORT:-10000}"
