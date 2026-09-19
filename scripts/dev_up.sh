#!/usr/bin/env bash
# One-command local bring-up for laptop testing (SQLite, free).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null; then
  echo "python3 is required"
  exit 1
fi
if ! command -v npm >/dev/null; then
  echo "npm/Node.js is required (https://nodejs.org)"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Creating .env for local SQLite..."
  ENC="$(python3 -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')"
  PEPPER="$(python3 -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')"
  SVC="$(python3 -c 'import secrets; print("mbs_" + secrets.token_urlsafe(32))')"
  ADM="$(python3 -c 'import secrets; print("mba_" + secrets.token_urlsafe(32))')"
  cat > .env <<EOF
DATABASE_URL=sqlite:///./memorybridge.db
ENCRYPTION_KEY=${ENC}
TOKEN_HASH_PEPPER=${PEPPER}
SERVICE_API_KEYS=${SVC}
ADMIN_API_KEY=${ADM}
PUBLIC_BASE_URL=http://localhost:8000
BILLING_SUCCESS_URL=http://localhost:8000/billing/success
BILLING_CANCEL_URL=http://localhost:8000/billing/cancel
RATE_LIMIT_REQUESTS=1000
RATE_LIMIT_WINDOW_SECONDS=60
METRICS_ENABLED=true
DEFAULT_TENANT_SLUG=default
EOF
  echo "Wrote .env (keep ADMIN_API_KEY private)"
fi

# Export .env for child processes
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

export PYTHONPATH=.
python3 -m alembic upgrade head

if [[ ! -d web/node_modules ]]; then
  (cd web && npm install)
fi
(cd web && npm run build)

echo ""
echo "============================================"
echo " MemoryBridge local is ready"
echo " Open: http://localhost:8000"
echo " API:  http://localhost:8000/api"
echo " Admin key is in .env (ADMIN_API_KEY)"
echo " Ctrl+C to stop"
echo "============================================"
echo ""

exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
