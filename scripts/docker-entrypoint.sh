#!/bin/sh
set -eu

echo "memorybridge: starting boot sequence"

echo "memorybridge: running schema repair"
python -m scripts.ensure_schema || python scripts/ensure_schema.py

i=1
while [ "$i" -le 10 ]; do
  echo "memorybridge: alembic upgrade head (attempt $i)"
  if alembic upgrade head; then
    echo "memorybridge: migrations complete"
    break
  fi
  if [ "$i" -eq 10 ]; then
    echo "memorybridge: FATAL alembic upgrade failed after $i attempts" >&2
    exit 1
  fi
  sleep 3
  i=$((i + 1))
done

PORT="${PORT:-8000}"
echo "memorybridge: starting uvicorn on 0.0.0.0:${PORT}"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
