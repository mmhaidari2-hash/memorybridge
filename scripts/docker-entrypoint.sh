#!/bin/sh
set -eu

echo "memorybridge: schema repair + create_all"
python scripts/ensure_schema.py

PORT="${PORT:-8000}"
echo "memorybridge: starting uvicorn on 0.0.0.0:${PORT}"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
