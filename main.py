from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from routers import auth, memory
Base.metadata.create_all(bind=engine)

app = FastAPI(title="MemoryBridge API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/v1")
app.include_router(memory.router, prefix="/v1")

@app.get("/v1/memory/status")
def status():
    return {"status": "ok", "service": "MemoryBridge"}
