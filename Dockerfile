# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

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
COPY --from=web-build --chown=memorybridge:memorybridge /web/dist ./web/dist

USER memorybridge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
