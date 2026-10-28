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
# Install Chromium plus runtime libraries explicitly. Playwright's --with-deps
# package list contains removed ttf-* packages on Debian Trixie (python:slim),
# which breaks production image builds before the browser can be installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libxcb1 libxkbcommon0 libasound2t64 libpango-1.0-0 libcairo2 \
    libcups2 libdrm2 libdbus-1-3 libglib2.0-0 libgtk-3-0 libgdk-pixbuf-2.0-0 \
    libxshmfence1 libfontconfig1 fonts-liberation fonts-noto-color-emoji \
    libvulkan1 libx11-xcb1 libxrender1 libxtst6 libegl1 libxss1 \
    && /app/.venv/bin/playwright install chromium \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/backend

# Run Family Coverage as a separate background process.
# It shares the same Fly volume/database but never participates in the
# FastAPI /search path. The trap terminates it together with uvicorn.
CMD ["sh", "-c", "cd /app/backend && /app/.venv/bin/python -m catalog_family_coverage & WORKER_PID=$!; trap 'kill $WORKER_PID 2>/dev/null || true; exit 143' TERM INT; trap 'kill $WORKER_PID 2>/dev/null || true' EXIT; /app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080"]
