from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import Depends

from app.config import get_settings
from app.database import get_db
from app.http_security import SecurityHeadersMiddleware
from app.metrics import metrics
from app.observability import RequestLoggingMiddleware
from app.request_limits import RequestSizeLimitMiddleware
from routers import admin, auth, billing, memory

# Fail closed on boot if required security configuration is missing.
get_settings()

app = FastAPI(
    title="MemoryBridge API",
    version="0.4.0-dev",
    description="Multi-tenant secure memory persistence layer for AI applications.",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)

app.include_router(auth.router, prefix="/v1")
app.include_router(memory.router, prefix="/v1")
app.include_router(billing.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "memorybridge",
        "version": "0.4.0-dev",
    }


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
