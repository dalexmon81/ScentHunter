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
# Keep the Playwright browser cache at the same absolute path during image
# build and runtime. Fly machines may expose HOME differently from the build
# stage; relying on Playwright's implicit ~/.cache path can leave Chromium
# installed in /root/.cache while runtime looks under /.cache.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# The restored Notino, Deloox and Amazon adapters require a real Chromium
# runtime. Install the browser and OS libraries in the final image, not just
# the Python Playwright package, so production has the executable at the
# exact path Playwright resolves when a retailer returns an interstitial.
RUN /app/.venv/bin/playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app/backend

# Run Family Coverage as a separate background process.
# It shares the same Fly volume/database but never participates in the
# FastAPI /search path. The trap terminates it together with uvicorn.
CMD ["sh", "-c", "cd /app/backend && /app/.venv/bin/uvicorn postgres_main:app --host 0.0.0.0 --port 8080"]
