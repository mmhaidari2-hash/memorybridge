from pathlib import Path
from contextlib import asynccontextmanager
import logging
import threading

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.http_security import SecurityHeadersMiddleware
from app.metrics import metrics
from app.observability import RequestLoggingMiddleware
from app.request_limits import RequestSizeLimitMiddleware
from routers import admin, auth, billing, memory

logger = logging.getLogger("memorybridge.boot")

# Fail closed on boot if required security configuration is missing.
get_settings()

WEB_DIST = Path(__file__).resolve().parent / "web" / "dist"


def _background_schema_repair() -> None:
    try:
        from scripts.ensure_schema import repair

        repair()
        logger.info("background_schema_repair_ok")
    except Exception:
        logger.exception("background_schema_repair_failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Heal drifted DBs after the server is already accepting /health.
    threading.Thread(target=_background_schema_repair, name="schema-repair", daemon=True).start()
    yield


app = FastAPI(
    title="MemoryBridge API",
    version="0.4.0-dev",
    description="Multi-tenant secure memory persistence layer for AI applications.",
    lifespan=lifespan,
)
_settings = get_settings()
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
# Explicit frontend origins only — never allow_origins=["*"] with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/v1")
app.include_router(memory.router, prefix="/v1")
app.include_router(billing.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")


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


@app.get("/metrics")
def prometheus_metrics():
    settings = get_settings()
    if not settings.metrics_enabled:
        return Response(status_code=404)
    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/api")
def api_root():
    return {
        "status": "ok",
        "service": "memorybridge",
        "version": "0.4.0-dev",
    }


def _spa_index():
    return FileResponse(WEB_DIST / "index.html")


if WEB_DIST.exists():
    assets_dir = WEB_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    @app.get("/")
    def marketing_home():
        return _spa_index()

    @app.get("/billing/success")
    def billing_success_page():
        return _spa_index()

    @app.get("/billing/cancel")
    def billing_cancel_page():
        return _spa_index()

    @app.get("/favicon.svg")
    def favicon():
        path = WEB_DIST / "favicon.svg"
        if path.exists():
            return FileResponse(path)
        return Response(status_code=404)
else:

    @app.get("/")
    def read_root():
        return {
            "status": "ok",
            "service": "memorybridge",
            "version": "0.4.0-dev",
            "marketing": "Build the site with: cd web && npm install && npm run build",
        }
