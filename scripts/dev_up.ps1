# One-command local bring-up for Windows PowerShell (SQLite, free).
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Require-Cmd($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Host "Missing required tool: $name" -ForegroundColor Red
    exit 1
  }
}

Require-Cmd python
Require-Cmd npm

if (-not (Test-Path ".env")) {
  Write-Host "Creating .env for local SQLite..."
  $enc = python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
  $pepper = python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
  $svc = python -c "import secrets; print('mbs_' + secrets.token_urlsafe(32))"
  $adm = python -c "import secrets; print('mba_' + secrets.token_urlsafe(32))"
  @"
DATABASE_URL=sqlite:///./memorybridge.db
ENCRYPTION_KEY=$enc
TOKEN_HASH_PEPPER=$pepper
SERVICE_API_KEYS=$svc
ADMIN_API_KEY=$adm
PUBLIC_BASE_URL=http://localhost:8000
BILLING_SUCCESS_URL=http://localhost:8000/billing/success
BILLING_CANCEL_URL=http://localhost:8000/billing/cancel
RATE_LIMIT_REQUESTS=1000
RATE_LIMIT_WINDOW_SECONDS=60
METRICS_ENABLED=true
DEFAULT_TENANT_SLUG=default
"@ | Set-Content -Encoding ascii .env
  Write-Host "Wrote .env"
}

Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $k, $v = $_ -split '=', 2
  if ($k -and $v) { Set-Item -Path "Env:$k" -Value $v }
}

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
python -m pip install -q -r requirements.txt

$env:PYTHONPATH = "."
python -m alembic upgrade head

if (-not (Test-Path "web\node_modules")) {
  Push-Location web
  npm install
  Pop-Location
}
Push-Location web
npm run build
Pop-Location

Write-Host ""
Write-Host "============================================"
Write-Host " MemoryBridge local is ready"
Write-Host " Open in LAPTOP browser: http://localhost:8000"
Write-Host " Ctrl+C to stop"
Write-Host "============================================"
Write-Host ""

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
