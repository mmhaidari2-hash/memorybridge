
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, memory

app = FastAPI(title="Memory Bridge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(memory.router)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Memory Bridge API is running"}
