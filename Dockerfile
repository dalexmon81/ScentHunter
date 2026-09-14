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

CMD ["sh", "-c", "cd /app/backend && /app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080"]
