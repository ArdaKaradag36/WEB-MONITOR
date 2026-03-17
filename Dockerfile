FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY watchdog/requirements.txt .

RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 1000 watchdog

COPY --from=builder /install /usr/local

COPY watchdog/ /app/

RUN mkdir -p /app/data \
 && chown -R watchdog:watchdog /app

USER watchdog

ENV WATCHDOG_DB_PATH=/app/data/watchdog.db \
    WATCHDOG_TARGETS_FILE=/app/config/targets.yaml

CMD ["python", "main.py", "--monitor"]

