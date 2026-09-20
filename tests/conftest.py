import base64
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SERVICE_API_KEY = "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz"
ADMIN_API_KEY = "mba_test_admin_key_abcdefghijklmnopqrstuvwxyz012345"
SERVICE_HEADERS = {"X-MemoryBridge-Key": SERVICE_API_KEY}
ADMIN_HEADERS = {"X-MemoryBridge-Admin-Key": ADMIN_API_KEY}

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENCRYPTION_KEY"] = base64.b64encode(b"x" * 32).decode("ascii")
os.environ.pop("ENCRYPTION_KEYS", None)
os.environ.pop("ENCRYPTION_ACTIVE_VERSION", None)
os.environ["SERVICE_API_KEYS"] = SERVICE_API_KEY
os.environ["ADMIN_API_KEY"] = ADMIN_API_KEY
os.environ["TOKEN_HASH_PEPPER"] = base64.b64encode(b"p" * 32).decode("ascii")
os.environ["RATE_LIMIT_REQUESTS"] = "1000"
os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "60"

from app.config import clear_settings_cache
from app.database import Base, get_db, set_session_factory
from app.rate_limit import rate_limiter
from main import app

clear_settings_cache()

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

set_session_factory(TestingSessionLocal)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture()
def api_client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    clear_settings_cache()
    app.dependency_overrides[get_db] = override_get_db
    return client


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
