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
    && addgroup --system memorybridge \
    && adduser --system --ingroup memorybridge memorybridge

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=memorybridge:memorybridge . .
COPY --from=web-build --chown=memorybridge:memorybridge /web/dist ./web/dist

RUN chmod +x /app/scripts/docker-entrypoint.sh

USER memorybridge

EXPOSE 8000

# Allow time for alembic + cold start before health probes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3)" || exit 1

# Railway injects PORT. Shell form matches prior successful deploys and expands ${PORT}.
# Entrypoint runs alembic upgrade head, then exec's uvicorn.
CMD ["sh", "-c", "exec /app/scripts/docker-entrypoint.sh"]
