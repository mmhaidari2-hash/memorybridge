from fastapi import Depends, FastAPI, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.http_security import SecurityHeadersMiddleware
from app.observability import RequestLoggingMiddleware
from app.service_auth import verify_service_api_key
from routers import auth
from routers.routers import memory

app = FastAPI(
    title="MemoryBridge API",
    version="0.3.0-dev",
    description="Secure memory persistence layer for AI applications.",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

protected_dependencies = [Depends(verify_service_api_key)]
app.include_router(auth.router, prefix="/v1", dependencies=protected_dependencies)
app.include_router(memory.router, prefix="/v1", dependencies=protected_dependencies)


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "memorybridge",
        "version": "0.3.0-dev",
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
