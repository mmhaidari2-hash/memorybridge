from fastapi import Depends, FastAPI, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.http_security import SecurityHeadersMiddleware
from app.observability import RequestLoggingMiddleware
from routers import api_keys, auth
from routers.routers import memory

app = FastAPI(
    title="MemoryBridge API",
    version="0.4.0-dev",
    description="Secure memory persistence layer for AI applications.",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router, prefix="/v1")
app.include_router(memory.router, prefix="/v1")
app.include_router(api_keys.router, prefix="/v1")


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
