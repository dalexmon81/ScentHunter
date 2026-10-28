FROM python:3.12.14 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN python -m venv .venv

COPY requirements.txt ./

RUN .venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12.14-slim

WORKDIR /app

COPY --from=builder /app/.venv .venv/
COPY . .
# The restored Notino and Amazon public-search adapters require a real Chromium
# runtime. Install the browser and OS libraries in the final image, not just the
# Python Playwright package, so production behaves like the tested browser path.
RUN /app/.venv/bin/playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/backend

# Run Family Coverage as a separate background process.
# It shares the same Fly volume/database but never participates in the
# FastAPI /search path. The trap terminates it together with uvicorn.
CMD ["sh", "-c", "cd /app/backend && /app/.venv/bin/python -m catalog_family_coverage & WORKER_PID=$!; trap 'kill $WORKER_PID 2>/dev/null || true; exit 143' TERM INT; trap 'kill $WORKER_PID 2>/dev/null || true' EXIT; /app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080"]
