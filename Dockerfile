FROM python:3.12.14 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN python -m venv .venv

COPY requirements.txt ./

RUN .venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12.14-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv .venv/
COPY . .
# The restored Notino and Amazon public-search adapters require a real Chromium
# runtime. Install the browser and OS libraries in the final image, not just the
# Python Playwright package, so production behaves like the tested browser path.
RUN /app/.venv/bin/playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/backend

# Bootstrap the canonical catalog before exposing the catalog-first frontend.
# Keep the existing legacy discovery/report workers running during the gradual
# cutover; the new catalog worker uses its own DB and queue files on the same
# mounted volume. Any migration/seed error fails startup instead of serving an
# empty or partially initialized canonical catalog.
CMD ["sh", "-c", "set -eu; cd /app/backend; /app/.venv/bin/python scripts/bootstrap_catalog.py; /app/.venv/bin/python -m catalog_family_coverage & FAMILY_PID=$!; /app/.venv/bin/python -m phase0_baseline_worker & PHASE0_PID=$!; /app/.venv/bin/python -m app.workers.sqlite_worker & INGESTION_PID=$!; cleanup(){ kill \"$FAMILY_PID\" \"$PHASE0_PID\" \"$INGESTION_PID\" 2>/dev/null || true; wait \"$FAMILY_PID\" 2>/dev/null || true; wait \"$PHASE0_PID\" 2>/dev/null || true; wait \"$INGESTION_PID\" 2>/dev/null || true; }; trap 'exit 143' TERM INT; trap cleanup EXIT; /app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080"]
