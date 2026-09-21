# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system memorybridge \
    && adduser --system --ingroup memorybridge memorybridge

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=memorybridge:memorybridge . .

# Optional frontend assets: build in CI/local and commit dist, or skip (API still boots).
# Multi-stage Node builds have been unreliable on this Railway service; keep image lean.
RUN chmod +x /app/scripts/docker-entrypoint.sh

USER memorybridge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3)" || exit 1

# Proven Railway pattern: shell CMD expands PORT; entrypoint migrates then serves.
CMD ["sh", "-c", "exec /app/scripts/docker-entrypoint.sh"]
