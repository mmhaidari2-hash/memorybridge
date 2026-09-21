#!/bin/sh
set -eu

# Apply schema before accepting traffic. Alembic is idempotent across restarts.
echo "memorybridge: running alembic upgrade head"
alembic upgrade head

PORT="${PORT:-8000}"
echo "memorybridge: starting uvicorn on 0.0.0.0:${PORT}"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
