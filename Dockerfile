# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system memorybridge \
    && adduser --system --ingroup memorybridge memorybridge

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=memorybridge:memorybridge . .
RUN chmod +x /app/scripts/docker-entrypoint.sh

USER memorybridge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=8 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3)" || exit 1

# Note: `;` not `&&` after repair/migrate so a non-fatal stamp still boots uvicorn
# only if migrate succeeds — migrate failure should still fail the boot.
CMD ["sh", "-c", "python scripts/ensure_schema.py && alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
