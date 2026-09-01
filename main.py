import os

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.http_security import SecurityHeadersMiddleware
from app.observability import RequestLoggingMiddleware
from app.runtime_validation import validate_runtime_config
from routers import account, api_keys, auth, billing
from routers.routers import memory


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must list explicit origins; wildcard is not allowed")
    return origins


# Customer-facing deployments must set APP_ENV=production. In that mode the
# process refuses to start with placeholder/missing secrets, non-HTTPS browser
# origins/redirects, or inconsistent Stripe Test/Live configuration.
validate_runtime_config()

app = FastAPI(
    title="MemoryBridge API",
    version="0.4.0-dev",
    description="Secure memory persistence layer for AI applications.",
)

allowed_origins = _cors_origins()
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-MemoryBridge-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router, prefix="/v1")
app.include_router(memory.router, prefix="/v1")
app.include_router(api_keys.router, prefix="/v1")
app.include_router(billing.router, prefix="/v1")
app.include_router(account.router, prefix="/v1")


@app.get("/")
def read_root():
    return {"status": "ok", "service": "memorybridge", "version": "0.4.0-dev"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def readiness(response: Response, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return {"status": "not_ready"}
    return {"status": "ready"}


@app.get("/app", include_in_schema=False)
def customer_app_entrypoint():
    return RedirectResponse(url="/app/landing.html", status_code=307)


# Serve the commercial UI from the API process as a same-origin option. This
# removes CORS from the critical customer path when deployed as a single
# service while preserving explicit CORS support for split frontend hosting.
app.mount("/app", StaticFiles(directory="web", html=True), name="customer-web")
