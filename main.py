from fastapi import Depends, FastAPI

from app.service_auth import verify_service_api_key
from routers import auth
from routers.routers import memory

app = FastAPI(
    title="MemoryBridge API",
    version="0.3.0-dev",
    description="Secure memory persistence layer for AI applications.",
)

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
