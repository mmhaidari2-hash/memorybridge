from fastapi import FastAPI
from routers import auth
from routers.routers import memory

app = FastAPI(
    title="MemoryBridge API",
    version="0.2.0",
    description="Secure memory persistence layer for AI applications.",
)

app.include_router(auth.router, prefix="/v1")
app.include_router(memory.router, prefix="/v1")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "memorybridge",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
