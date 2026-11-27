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
# The restored Notino, Amazon and Deloox public-page adapters require a real
# Chromium runtime. Pin Playwright's browser cache to the same absolute path at
# build time and runtime; Fly workers expose HOME=/, so the default /root cache
# is not visible to the running scraper process.
ENV PLAYWRIGHT_BROWSERS_PATH=/.cache/ms-playwright
RUN /app/.venv/bin/playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/backend

# Run Family Coverage as a separate background process.
# It shares the same Fly volume/database but never participates in the
# FastAPI /search path. The trap terminates it together with uvicorn.
CMD ["sh", "-c", "cd /app/backend && /app/.venv/bin/uvicorn postgres_main:app --host 0.0.0.0 --port 8080"]
