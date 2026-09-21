# syntax=docker/dockerfile:1

# --- Frontend (static assets served by FastAPI) ---
FROM node:22-bookworm-slim AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- API runtime ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Minimal OS packages: certs for TLS (Stripe/Postgres/Redis), curl for ops probes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 memorybridge \
    && adduser --system --uid 10001 --ingroup memorybridge --home /app memorybridge

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=memorybridge:memorybridge . .
COPY --from=web-build --chown=memorybridge:memorybridge /web/dist ./web/dist

RUN chmod +x /app/scripts/docker-entrypoint.sh

USER memorybridge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)" || exit 1

# Migrations then Uvicorn; PORT is injected by Railway (defaults to 8000).
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
